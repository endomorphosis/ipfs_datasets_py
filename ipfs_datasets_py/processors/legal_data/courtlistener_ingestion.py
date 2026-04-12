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
from typing import Any, Dict, Iterable, List, Mapping, Optional
from urllib.parse import urljoin, urlparse

try:
    from ..legal_scrapers.shared_fetch_cache import SharedFetchCache
except Exception:  # pragma: no cover
    SharedFetchCache = None  # type: ignore[assignment]

COURTLISTENER_API_ROOT = "https://www.courtlistener.com/api/rest/v4/"
COURTLISTENER_RECAP_FETCH_URL = urljoin(COURTLISTENER_API_ROOT, "recap-fetch/")
COURTLISTENER_RECAP_FETCH_REQUEST_TYPES = {
    "html_docket": 1,
    "pdf": 2,
    "attachment_page": 3,
}

__all__ = [
    "COURTLISTENER_API_ROOT",
    "COURTLISTENER_RECAP_FETCH_URL",
    "COURTLISTENER_RECAP_FETCH_REQUEST_TYPES",
    "attach_available_courtlistener_recap_evidence_to_docket",
    "attach_public_courtlistener_filing_pdfs_to_docket",
    "build_packaged_docket_acquisition_plan",
    "execute_packaged_docket_acquisition_plan",
    "CourtListenerIngestionError",
    "build_courtlistener_recap_fetch_payload",
    "extract_courtlistener_public_filing_pdf_texts",
    "fetch_courtlistener_docket",
    "find_rich_courtlistener_docket",
    "fetch_random_courtlistener_docket",
    "probe_courtlistener_public_filing_pdfs",
    "get_courtlistener_recap_fetch_request",
    "fetch_pacer_document_with_browser",
    "resolve_pacer_client_code",
    "resolve_pacer_password",
    "resolve_pacer_username",
    "probe_courtlistener_document_acquisition_target",
    "sample_random_courtlistener_dockets_batch",
    "resolve_courtlistener_api_token",
    "build_packaged_docket_recap_fetch_preflight",
    "submit_courtlistener_recap_fetch_request",
    "submit_packaged_docket_recap_fetch_requests",
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


def resolve_pacer_username(username: str | None = None) -> str | None:
    """Resolve a PACER username from explicit input, env, or shared secrets."""

    if username:
        return username.strip() or None

    for env_key in ("PACER_USERNAME", "COURTLISTENER_PACER_USERNAME"):
        env_value = str(os.environ.get(env_key) or "").strip()
        if env_value:
            return env_value

    for secret_key in ("PACER_USERNAME", "COURTLISTENER_PACER_USERNAME"):
        shared_secret = _load_shared_secret_value(secret_key)
        if shared_secret:
            return shared_secret
    return None


def resolve_pacer_password(password: str | None = None) -> str | None:
    """Resolve a PACER password from explicit input, env, or shared secrets."""

    if password:
        return password.strip() or None

    for env_key in ("PACER_PASSWORD", "COURTLISTENER_PACER_PASSWORD"):
        env_value = str(os.environ.get(env_key) or "").strip()
        if env_value:
            return env_value

    for secret_key in ("PACER_PASSWORD", "COURTLISTENER_PACER_PASSWORD"):
        shared_secret = _load_shared_secret_value(secret_key)
        if shared_secret:
            return shared_secret
    return None


def resolve_pacer_client_code(client_code: str | None = None) -> str | None:
    """Resolve an optional PACER client code from explicit input, env, or shared secrets."""

    if client_code:
        return client_code.strip() or None

    for env_key in ("PACER_CLIENT_CODE", "COURTLISTENER_PACER_CLIENT_CODE"):
        env_value = str(os.environ.get(env_key) or "").strip()
        if env_value:
            return env_value

    for secret_key in ("PACER_CLIENT_CODE", "COURTLISTENER_PACER_CLIENT_CODE"):
        shared_secret = _load_shared_secret_value(secret_key)
        if shared_secret:
            return shared_secret
    return None


def build_courtlistener_recap_fetch_payload(
    *,
    queue_row: Mapping[str, Any] | None = None,
    pacer_username: str | None = None,
    pacer_password: str | None = None,
    client_code: str | None = None,
    request_type: str | int | None = None,
    court: str | None = None,
    docket: str | int | None = None,
    docket_number: str | None = None,
    pacer_case_id: str | None = None,
    recap_document_id: str | int | None = None,
    de_number_start: int | None = None,
    de_number_end: int | None = None,
    show_parties_and_counsel: bool | None = True,
    show_terminated_parties: bool | None = False,
    show_list_of_member_cases: bool | None = False,
) -> Dict[str, Any]:
    """Build a CourtListener RECAP Fetch payload from an acquisition queue row."""

    queue = dict(queue_row or {})
    acquisition_kind = str(queue.get("acquisition_kind") or "").strip().lower()
    queue_notes = _parse_possible_json_text(queue.get("notes_json")) or {}

    resolved_username = resolve_pacer_username(pacer_username)
    resolved_password = resolve_pacer_password(pacer_password)
    if not resolved_username or not resolved_password:
        raise CourtListenerIngestionError(
            "PACER credentials are required for CourtListener RECAP Fetch submission."
        )
    resolved_client_code = resolve_pacer_client_code(client_code)

    resolved_request_type = _normalize_recap_fetch_request_type(
        request_type,
        acquisition_kind=acquisition_kind,
        recap_document_id=recap_document_id or queue.get("recap_document_id") or queue.get("courtlistener_recap_document_id"),
    )
    resolved_court = _normalize_courtlistener_court_reference(
        court or queue.get("court") or queue_notes.get("court") or ""
    )
    resolved_docket_number = str(
        docket_number
        or queue.get("docket_number")
        or queue_notes.get("docket_number")
        or ""
    ).strip()
    resolved_pacer_case_id = str(
        pacer_case_id
        or queue.get("pacer_case_id")
        or queue_notes.get("pacer_case_id")
        or ""
    ).strip()
    resolved_recap_document_id = str(
        recap_document_id
        or queue.get("recap_document_id")
        or queue.get("courtlistener_recap_document_id")
        or queue_notes.get("recap_document_id")
        or ""
    ).strip()
    resolved_docket = str(
        docket
        or queue.get("courtlistener_docket_id")
        or queue.get("docket_id")
        or queue_notes.get("courtlistener_docket_id")
        or ""
    ).strip()

    normalized_de_start = de_number_start
    normalized_de_end = de_number_end
    document_number_text = str(queue.get("document_number") or "").strip()
    if normalized_de_start is None and normalized_de_end is None and re.fullmatch(r"\d+", document_number_text):
        normalized_de_start = int(document_number_text)
        normalized_de_end = int(document_number_text)

    payload: Dict[str, Any] = {
        "request_type": resolved_request_type,
        "pacer_username": resolved_username,
        "pacer_password": resolved_password,
    }
    if resolved_client_code:
        payload["client_code"] = resolved_client_code

    if resolved_request_type == COURTLISTENER_RECAP_FETCH_REQUEST_TYPES["html_docket"]:
        if not resolved_court or not (resolved_docket_number or resolved_pacer_case_id or resolved_docket):
            raise CourtListenerIngestionError(
                "HTML docket RECAP Fetch requires a court plus docket_number, pacer_case_id, or CourtListener docket id."
            )
        if resolved_court:
            payload["court"] = resolved_court
        if resolved_docket:
            payload["docket"] = int(resolved_docket) if resolved_docket.isdigit() else resolved_docket
        if resolved_docket_number:
            payload["docket_number"] = resolved_docket_number
        if resolved_pacer_case_id:
            payload["pacer_case_id"] = resolved_pacer_case_id
        if normalized_de_start is not None:
            payload["de_number_start"] = int(normalized_de_start)
        if normalized_de_end is not None:
            payload["de_number_end"] = int(normalized_de_end)
        if show_parties_and_counsel is not None:
            payload["show_parties_and_counsel"] = bool(show_parties_and_counsel)
        if show_terminated_parties is not None:
            payload["show_terminated_parties"] = bool(show_terminated_parties)
        if show_list_of_member_cases is not None:
            payload["show_list_of_member_cases"] = bool(show_list_of_member_cases)
        return payload

    if not resolved_recap_document_id:
        raise CourtListenerIngestionError(
            "PDF or attachment-page RECAP Fetch requires a recap_document id."
        )
    payload["recap_document"] = int(resolved_recap_document_id) if resolved_recap_document_id.isdigit() else resolved_recap_document_id
    return payload


def submit_courtlistener_recap_fetch_request(
    *,
    queue_row: Mapping[str, Any] | None = None,
    api_token: str | None = None,
    pacer_username: str | None = None,
    pacer_password: str | None = None,
    client_code: str | None = None,
    request_type: str | int | None = None,
    court: str | None = None,
    docket: str | int | None = None,
    docket_number: str | None = None,
    pacer_case_id: str | None = None,
    recap_document_id: str | int | None = None,
    de_number_start: int | None = None,
    de_number_end: int | None = None,
    show_parties_and_counsel: bool | None = True,
    show_terminated_parties: bool | None = False,
    show_list_of_member_cases: bool | None = False,
    requests_module: Any | None = None,
    request_timeout_seconds: float = 30.0,
) -> Dict[str, Any]:
    """Submit a CourtListener RECAP Fetch job."""

    if requests_module is None:
        try:
            import requests as requests_module
        except ImportError as exc:  # pragma: no cover
            raise CourtListenerIngestionError(
                "CourtListener RECAP Fetch requires the 'requests' package."
            ) from exc

    token = resolve_courtlistener_api_token(api_token)
    if not token:
        raise CourtListenerIngestionError("A CourtListener API token is required for RECAP Fetch submission.")

    payload = build_courtlistener_recap_fetch_payload(
        queue_row=queue_row,
        pacer_username=pacer_username,
        pacer_password=pacer_password,
        client_code=client_code,
        request_type=request_type,
        court=court,
        docket=docket,
        docket_number=docket_number,
        pacer_case_id=pacer_case_id,
        recap_document_id=recap_document_id,
        de_number_start=de_number_start,
        de_number_end=de_number_end,
        show_parties_and_counsel=show_parties_and_counsel,
        show_terminated_parties=show_terminated_parties,
        show_list_of_member_cases=show_list_of_member_cases,
    )
    response_data = _post_json(
        COURTLISTENER_RECAP_FETCH_URL,
        headers={"Authorization": f"Token {token}"},
        json_payload=payload,
        requests_module=requests_module,
        request_timeout_seconds=request_timeout_seconds,
    )
    return {
        "status": "submitted",
        "request": dict(response_data),
        "request_id": response_data.get("id"),
        "request_type": payload.get("request_type"),
        "payload_preview": _redact_recap_fetch_payload(payload),
    }


def get_courtlistener_recap_fetch_request(
    request_id: str | int,
    *,
    api_token: str | None = None,
    requests_module: Any | None = None,
    request_timeout_seconds: float = 30.0,
) -> Dict[str, Any]:
    """Load a CourtListener RECAP Fetch request by id."""

    if requests_module is None:
        try:
            import requests as requests_module
        except ImportError as exc:  # pragma: no cover
            raise CourtListenerIngestionError(
                "CourtListener RECAP Fetch requires the 'requests' package."
            ) from exc

    token = resolve_courtlistener_api_token(api_token)
    if not token:
        raise CourtListenerIngestionError("A CourtListener API token is required to inspect RECAP Fetch status.")
    request_id_text = str(request_id or "").strip()
    if not request_id_text:
        raise CourtListenerIngestionError("A non-empty CourtListener RECAP Fetch request id is required.")
    request_url = urljoin(COURTLISTENER_RECAP_FETCH_URL, f"{request_id_text}/")
    response_data = _get_json(
        request_url,
        headers={"Authorization": f"Token {token}"},
        requests_module=requests_module,
        request_timeout_seconds=request_timeout_seconds,
    )
    return dict(response_data)


def submit_packaged_docket_recap_fetch_requests(
    manifest_path: str | Path,
    *,
    api_token: str | None = None,
    pacer_username: str | None = None,
    pacer_password: str | None = None,
    client_code: str | None = None,
    requests_module: Any | None = None,
    request_timeout_seconds: float = 30.0,
    only_ready: bool = True,
) -> Dict[str, Any]:
    """Submit CourtListener RECAP Fetch jobs for a packaged docket's acquisition queue."""

    from .docket_packaging import DocketDatasetPackager

    packager = DocketDatasetPackager()
    minimal_view = packager.load_minimal_dataset_view(manifest_path)
    acquisition_queue = [
        dict(item)
        for item in list(minimal_view.get("acquisition_queue") or [])
        if isinstance(item, dict)
    ]
    if only_ready:
        acquisition_queue = [item for item in acquisition_queue if bool(item.get("ready_for_fetch"))]

    context = _resolve_packaged_courtlistener_fetch_context(minimal_view)
    submissions: List[Dict[str, Any]] = []
    seen_docket_jobs: set[tuple[str, str, str, str]] = set()

    for queue_row in acquisition_queue:
        acquisition_kind = str(queue_row.get("acquisition_kind") or "").strip().lower()
        if acquisition_kind != "pacer_gate":
            continue
        docket_job_key = (
            str(context.get("court") or ""),
            str(context.get("docket_number") or ""),
            str(context.get("pacer_case_id") or ""),
            str(context.get("courtlistener_docket_id") or ""),
        )
        if docket_job_key in seen_docket_jobs:
            continue
        submission = submit_courtlistener_recap_fetch_request(
            queue_row=queue_row,
            api_token=api_token,
            pacer_username=pacer_username,
            pacer_password=pacer_password,
            client_code=client_code,
            request_type="html_docket",
            court=str(context.get("court") or ""),
            docket=str(context.get("courtlistener_docket_id") or ""),
            docket_number=str(context.get("docket_number") or ""),
            pacer_case_id=str(context.get("pacer_case_id") or ""),
            requests_module=requests_module,
            request_timeout_seconds=request_timeout_seconds,
        )
        submission["queue_row"] = {
            "queue_id": str(queue_row.get("queue_id") or ""),
            "filing_id": str(queue_row.get("filing_id") or ""),
            "title": str(queue_row.get("title") or ""),
        }
        submissions.append(submission)
        seen_docket_jobs.add(docket_job_key)

    return {
        "status": "submitted" if submissions else "noop",
        "submission_count": len(submissions),
        "submissions": submissions,
        "context": context,
    }


def build_packaged_docket_recap_fetch_preflight(
    manifest_path: str | Path,
    *,
    api_token: str | None = None,
    pacer_username: str | None = None,
    pacer_password: str | None = None,
    client_code: str | None = None,
    only_ready: bool = True,
) -> Dict[str, Any]:
    """Summarize whether a packaged docket is ready for CourtListener RECAP Fetch."""

    from .docket_packaging import DocketDatasetPackager

    packager = DocketDatasetPackager()
    minimal_view = packager.load_minimal_dataset_view(manifest_path)
    acquisition_queue = [
        dict(item)
        for item in list(minimal_view.get("acquisition_queue") or [])
        if isinstance(item, dict)
    ]
    if only_ready:
        acquisition_queue = [item for item in acquisition_queue if bool(item.get("ready_for_fetch"))]

    context = _resolve_packaged_courtlistener_fetch_context(minimal_view)
    pacer_gate_rows = [
        item
        for item in acquisition_queue
        if str(item.get("acquisition_kind") or "").strip().lower() == "pacer_gate"
    ]
    resolved_api_token = resolve_courtlistener_api_token(api_token)
    resolved_pacer_username = resolve_pacer_username(pacer_username)
    resolved_pacer_password = resolve_pacer_password(pacer_password)
    resolved_client_code = resolve_pacer_client_code(client_code)

    payload_preview: Dict[str, Any] | None = None
    preview_error = ""
    if pacer_gate_rows:
        try:
            payload_preview = _redact_recap_fetch_payload(
                build_courtlistener_recap_fetch_payload(
                    queue_row=pacer_gate_rows[0],
                    pacer_username=resolved_pacer_username,
                    pacer_password=resolved_pacer_password,
                    client_code=resolved_client_code,
                    request_type="html_docket",
                    court=str(context.get("court") or ""),
                    docket=str(context.get("courtlistener_docket_id") or ""),
                    docket_number=str(context.get("docket_number") or ""),
                    pacer_case_id=str(context.get("pacer_case_id") or ""),
                )
            )
        except Exception as exc:
            preview_error = str(exc)

    checks = {
        "has_courtlistener_api_token": bool(resolved_api_token),
        "has_pacer_username": bool(resolved_pacer_username),
        "has_pacer_password": bool(resolved_pacer_password),
        "has_pacer_client_code": bool(resolved_client_code),
        "has_pacer_gate_rows": bool(pacer_gate_rows),
        "has_court": bool(str(context.get("court") or "").strip()),
        "has_docket_number": bool(str(context.get("docket_number") or "").strip()),
        "has_courtlistener_docket_id": bool(str(context.get("courtlistener_docket_id") or "").strip()),
    }
    ready = all(
        [
            checks["has_courtlistener_api_token"],
            checks["has_pacer_username"],
            checks["has_pacer_password"],
            checks["has_pacer_gate_rows"],
            checks["has_court"],
            checks["has_docket_number"] or checks["has_courtlistener_docket_id"],
            not preview_error,
        ]
    )
    return {
        "status": "ready" if ready else "not_ready",
        "ready": bool(ready),
        "queue_row_count": len(acquisition_queue),
        "pacer_gate_row_count": len(pacer_gate_rows),
        "checks": checks,
        "context": context,
        "sample_queue_rows": [
            {
                "queue_id": str(item.get("queue_id") or ""),
                "title": str(item.get("title") or ""),
                "document_number": str(item.get("document_number") or ""),
                "acquisition_kind": str(item.get("acquisition_kind") or ""),
                "ready_for_fetch": bool(item.get("ready_for_fetch")),
            }
            for item in pacer_gate_rows[:3]
        ],
        **({"payload_preview": payload_preview} if payload_preview else {}),
        **({"preview_error": preview_error} if preview_error else {}),
    }


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
        docket_data.get("court_id")
        or docket_data.get("court_name")
        or docket_data.get("court_full_name")
        or docket_data.get("court")
        or ""
    ).strip()
    docket_number = str(
        docket_data.get("docket_number")
        or docket_data.get("docketNumber")
        or docket_data.get("docket_number_raw")
        or ""
    ).strip()
    pacer_case_id = str(
        docket_data.get("pacer_case_id")
        or docket_data.get("pacerCaseId")
        or ""
    ).strip()
    court_name = str(
        docket_data.get("court_name")
        or docket_data.get("court_full_name")
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
            "court_id": str(docket_data.get("court_id") or "").strip(),
            "court_name": court_name,
            "docket_number": docket_number,
            "pacer_case_id": pacer_case_id,
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


def build_packaged_docket_acquisition_plan(
    manifest_path: str | Path,
    *,
    only_ready: bool = True,
    include_browser_probe: bool = False,
) -> Dict[str, Any]:
    from .docket_packaging import DocketDatasetPackager

    minimal_view = DocketDatasetPackager().load_minimal_dataset_view(manifest_path)
    acquisition_queue = [dict(item) for item in list(minimal_view.get("acquisition_queue") or []) if isinstance(item, Mapping)]
    if only_ready:
        acquisition_queue = [item for item in acquisition_queue if bool(item.get("ready_for_fetch"))]

    plan_rows: List[Dict[str, Any]] = []
    for queue_row in acquisition_queue:
        notes = _parse_possible_json_text(queue_row.get("notes_json")) or {}
        source_url = str(queue_row.get("source_url") or "").strip()
        acquisition_url = str(queue_row.get("acquisition_url") or "").strip()
        acquisition_kind = str(queue_row.get("acquisition_kind") or "").strip()
        probe_url = source_url or acquisition_url
        browser_probe: Dict[str, Any] | None = None
        if include_browser_probe and probe_url:
            try:
                browser_probe = probe_courtlistener_document_acquisition_target(probe_url)
            except Exception as exc:
                browser_probe = {
                    "status": "error",
                    "url": probe_url,
                    "error": str(exc),
                }
        direct_target_url = (
            str((browser_probe or {}).get("pacer_purchase_url") or "").strip()
            or str((browser_probe or {}).get("download_url") or "").strip()
            or acquisition_url
            or source_url
        )
        plan_rows.append(
            {
                "queue_id": str(queue_row.get("queue_id") or ""),
                "filing_id": str(queue_row.get("filing_id") or ""),
                "document_id": str(queue_row.get("document_id") or ""),
                "document_number": str(queue_row.get("document_number") or ""),
                "title": str(queue_row.get("title") or ""),
                "acquisition_kind": acquisition_kind,
                "extractor_plan": str(queue_row.get("extractor_plan") or ""),
                "ready_for_fetch": bool(queue_row.get("ready_for_fetch")),
                "source_url": source_url,
                "acquisition_url": acquisition_url,
                "direct_target_url": direct_target_url,
                "target_source": (
                    "courtlistener_document_probe"
                    if browser_probe and str((browser_probe or {}).get("pacer_purchase_url") or "").strip()
                    else "queue"
                ),
                "browser_probe": browser_probe,
                "notes": notes,
            }
        )

    return {
        "status": "success",
        "manifest_path": str(Path(manifest_path)),
        "row_count": len(plan_rows),
        "ready_row_count": sum(1 for row in plan_rows if bool(row.get("ready_for_fetch"))),
        "probe_enabled": bool(include_browser_probe),
        "rows": plan_rows,
    }


def execute_packaged_docket_acquisition_plan(
    manifest_path: str | Path,
    *,
    only_ready: bool = True,
    include_browser_probe: bool = True,
    fetch_content: bool = True,
    request_timeout_seconds: float = 30.0,
    requests_module: Any | None = None,
) -> Dict[str, Any]:
    plan = build_packaged_docket_acquisition_plan(
        manifest_path,
        only_ready=only_ready,
        include_browser_probe=include_browser_probe,
    )
    rows = [dict(item) for item in list(plan.get("rows") or []) if isinstance(item, Mapping)]
    execution_rows: List[Dict[str, Any]] = []
    for row in rows:
        execution = dict(row)
        if fetch_content and str(row.get("direct_target_url") or "").strip():
            try:
                fetch_result = _fetch_acquisition_target(
                    str(row.get("direct_target_url") or ""),
                    request_timeout_seconds=request_timeout_seconds,
                    requests_module=requests_module,
                )
            except Exception as exc:
                fetch_result = {
                    "status": "error",
                    "error": str(exc),
                }
        else:
            fetch_result = {
                "status": "planned",
                "fetch_content": bool(fetch_content),
            }
        execution["fetch_result"] = fetch_result
        execution_rows.append(execution)

    return {
        "status": "success",
        "manifest_path": str(Path(manifest_path)),
        "row_count": len(execution_rows),
        "fetched_count": sum(1 for row in execution_rows if dict(row.get("fetch_result") or {}).get("status") == "fetched"),
        "auth_required_count": sum(
            1 for row in execution_rows if dict(row.get("fetch_result") or {}).get("status") == "authentication_required"
        ),
        "planned_count": sum(1 for row in execution_rows if dict(row.get("fetch_result") or {}).get("status") == "planned"),
        "rows": execution_rows,
    }


def probe_courtlistener_public_filing_pdfs(filing_url: str) -> Dict[str, Any]:
    return asyncio.run(_probe_courtlistener_public_filing_pdfs_async(filing_url))


def extract_courtlistener_public_filing_pdf_texts(
    filing_url: str,
    *,
    max_pdfs: int = 10,
    request_timeout_seconds: float = 30.0,
    requests_module: Any | None = None,
) -> Dict[str, Any]:
    probe = probe_courtlistener_public_filing_pdfs(filing_url)
    pdf_urls = [
        str(item.get("href") or "").strip()
        for item in list(probe.get("pdf_links") or [])
        if isinstance(item, Mapping) and str(item.get("href") or "").strip()
    ]
    deduped_pdf_urls: List[str] = []
    seen_pdf_urls: set[str] = set()
    for pdf_url in pdf_urls:
        if pdf_url in seen_pdf_urls:
            continue
        seen_pdf_urls.add(pdf_url)
        deduped_pdf_urls.append(pdf_url)
    pdf_urls = deduped_pdf_urls
    if max_pdfs > 0:
        pdf_urls = pdf_urls[: int(max_pdfs)]

    results: List[Dict[str, Any]] = []
    for url in pdf_urls:
        results.append(
            _fetch_public_pdf_text(
                url,
                request_timeout_seconds=request_timeout_seconds,
                requests_module=requests_module,
            )
        )

    return {
        "status": "success",
        "filing_url": filing_url,
        "pdf_count": len(results),
        "results": results,
        "probe": probe,
    }


def attach_public_courtlistener_filing_pdfs_to_docket(
    docket_payload: Dict[str, Any],
    filing_url: str,
    *,
    max_pdfs: int = 10,
    request_timeout_seconds: float = 30.0,
    requests_module: Any | None = None,
) -> Dict[str, Any]:
    enriched = dict(docket_payload or {})
    documents = [dict(item) for item in list(enriched.get("documents") or []) if isinstance(item, Mapping)]
    extraction = extract_courtlistener_public_filing_pdf_texts(
        filing_url,
        max_pdfs=max_pdfs,
        request_timeout_seconds=request_timeout_seconds,
        requests_module=requests_module,
    )
    probe = dict(extraction.get("probe") or {})
    title_hint = str(probe.get("title") or "").strip()

    for index, item in enumerate(list(extraction.get("results") or []), start=1):
        if not isinstance(item, Mapping):
            continue
        extracted_text = str(item.get("text") or item.get("text_preview") or "").strip()
        text_length = int(item.get("text_length") or 0)
        if not extracted_text and text_length <= 0:
            continue
        pdf_url = str(item.get("url") or "").strip()
        document_number = ""
        pdf_filename = pdf_url.rsplit("/", 1)[-1] if pdf_url else ""
        if pdf_filename.endswith(".pdf"):
            pdf_filename = pdf_filename[:-4]
        filename_parts = [part for part in pdf_filename.split(".") if part]
        if filename_parts:
            maybe_number = filename_parts[-1]
            if maybe_number.isdigit():
                document_number = maybe_number
        text_extraction = {
            "source": "courtlistener_public_filing_pdf",
            "method": str(item.get("extraction_method") or "unknown"),
            "text_length": text_length,
        }
        documents.append(
            {
                "id": f"{str(enriched.get('docket_id') or 'docket')}_public_pdf_{index}",
                "title": f"{title_hint or 'CourtListener public filing PDF'} PDF part {index}",
                "text": extracted_text,
                "document_number": document_number,
                "source_url": pdf_url or filing_url,
                "document_type": "courtlistener_public_filing_pdf",
                "text_extraction": dict(text_extraction),
                "metadata": {
                    "text_extraction": dict(text_extraction),
                    "public_filing_pdf": {
                        "filing_url": filing_url,
                        "pdf_url": pdf_url,
                        "byte_count": int(item.get("byte_count") or 0),
                    },
                },
            }
        )

    metadata = dict(enriched.get("metadata") or {})
    attachments = list(metadata.get("public_filing_pdf_extractions") or [])
    attachments.append(
        {
            "filing_url": filing_url,
            "pdf_count": int(extraction.get("pdf_count") or 0),
            "title": title_hint,
        }
    )
    metadata["public_filing_pdf_extractions"] = attachments
    enriched["metadata"] = metadata
    enriched["documents"] = documents
    return enriched


def attach_available_courtlistener_recap_evidence_to_docket(
    docket_payload: Dict[str, Any],
    *,
    max_documents: Optional[int] = None,
    request_timeout_seconds: float = 30.0,
    requests_module: Any | None = None,
) -> Dict[str, Any]:
    enriched = dict(docket_payload or {})
    documents = [dict(item) for item in list(enriched.get("documents") or []) if isinstance(item, Mapping)]
    seen_urls: set[str] = {
        str(item.get("source_url") or "").strip()
        for item in documents
        if str(item.get("source_url") or "").strip()
    }
    available_count = 0
    attached_count = 0
    skipped_count = 0

    for document in list(documents):
        if max_documents is not None and attached_count >= int(max_documents):
            break
        metadata = dict(document.get("metadata") or {})
        raw = dict(metadata.get("raw") or {})
        for recap in list(raw.get("recap_documents") or []):
            if max_documents is not None and attached_count >= int(max_documents):
                break
            if not isinstance(recap, Mapping):
                continue
            if not bool(recap.get("is_available")):
                continue
            available_count += 1

            recap_id = str(recap.get("id") or "").strip()
            plain_text = str(recap.get("plain_text") or "").strip()
            filepath_local = str(recap.get("filepath_local") or "").strip()
            filepath_ia = str(recap.get("filepath_ia") or "").strip()
            source_url = ""
            if filepath_local:
                source_url = filepath_local if filepath_local.startswith("http") else f"https://storage.courtlistener.com/{filepath_local.lstrip('/')}"
            elif filepath_ia:
                source_url = filepath_ia

            if source_url and source_url in seen_urls:
                skipped_count += 1
                continue

            text = plain_text
            extraction_method = "courtlistener_plain_text"
            byte_count = 0
            if not text and source_url:
                fetched = _fetch_public_pdf_text(
                    source_url,
                    request_timeout_seconds=request_timeout_seconds,
                    requests_module=requests_module,
                )
                text = str(fetched.get("text") or fetched.get("text_preview") or "").strip()
                extraction_method = str(fetched.get("extraction_method") or "courtlistener_public_pdf").strip() or "courtlistener_public_pdf"
                byte_count = int(fetched.get("byte_count") or 0)

            if not text:
                skipped_count += 1
                continue

            title = str(document.get("title") or "").strip() or f"RECAP document {recap_id or attached_count + 1}"
            document_number = str(recap.get("document_number") or document.get("document_number") or "").strip()
            text_extraction = {
                "source": "courtlistener_public_recap_document",
                "method": extraction_method,
                "text_length": len(text),
            }
            if source_url:
                seen_urls.add(source_url)
            documents.append(
                {
                    "id": f"{str(enriched.get('docket_id') or 'docket')}_recap_{recap_id or attached_count + 1}",
                    "title": title,
                    "text": text,
                    "document_number": document_number,
                    "source_url": source_url or str(document.get("source_url") or ""),
                    "document_type": "courtlistener_public_recap_document",
                    "text_extraction": dict(text_extraction),
                    "metadata": {
                        "text_extraction": dict(text_extraction),
                        "public_recap_document": {
                            "recap_document_id": recap_id,
                            "filepath_local": filepath_local,
                            "filepath_ia": filepath_ia,
                            "byte_count": byte_count,
                            "page_count": recap.get("page_count"),
                            "pacer_doc_id": recap.get("pacer_doc_id"),
                            "ocr_status": recap.get("ocr_status"),
                            "is_available": bool(recap.get("is_available")),
                        },
                    },
                }
            )
            attached_count += 1

    metadata = dict(enriched.get("metadata") or {})
    metadata["public_recap_evidence_summary"] = {
        "available_recap_document_count": available_count,
        "attached_recap_document_count": attached_count,
        "skipped_recap_document_count": skipped_count,
    }
    enriched["metadata"] = metadata
    enriched["documents"] = documents
    return enriched


def fetch_pacer_document_with_browser(
    target_url: str,
    *,
    pacer_username: str | None = None,
    pacer_password: str | None = None,
    pacer_client_code: str | None = None,
    request_timeout_seconds: float = 30.0,
) -> Dict[str, Any]:
    async def _runner() -> Dict[str, Any]:
        try:
            return await asyncio.wait_for(
                _fetch_pacer_document_with_browser_async(
                    target_url,
                    pacer_username=pacer_username,
                    pacer_password=pacer_password,
                    pacer_client_code=pacer_client_code,
                    request_timeout_seconds=request_timeout_seconds,
                ),
                timeout=max(5.0, float(request_timeout_seconds or 30.0) + 5.0),
            )
        except asyncio.TimeoutError:
            return {
                "status": "timeout",
                "target_url": target_url,
                "final_url": target_url,
                "title": "",
                "body_preview": "",
            }

    return asyncio.run(_runner())


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


def _normalize_recap_fetch_request_type(
    request_type: str | int | None,
    *,
    acquisition_kind: str = "",
    recap_document_id: Any = None,
) -> int:
    if isinstance(request_type, int):
        if request_type in COURTLISTENER_RECAP_FETCH_REQUEST_TYPES.values():
            return request_type
        raise CourtListenerIngestionError(f"Unsupported CourtListener RECAP Fetch request type: {request_type}")

    normalized = str(request_type or "").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in COURTLISTENER_RECAP_FETCH_REQUEST_TYPES:
        return COURTLISTENER_RECAP_FETCH_REQUEST_TYPES[normalized]

    normalized_kind = str(acquisition_kind or "").strip().lower()
    if recap_document_id:
        if normalized_kind == "attachment_page":
            return COURTLISTENER_RECAP_FETCH_REQUEST_TYPES["attachment_page"]
        return COURTLISTENER_RECAP_FETCH_REQUEST_TYPES["pdf"]
    return COURTLISTENER_RECAP_FETCH_REQUEST_TYPES["html_docket"]


def _redact_recap_fetch_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    preview = dict(payload or {})
    if "pacer_password" in preview:
        preview["pacer_password"] = "***"
    if "pacer_username" in preview:
        preview["pacer_username"] = str(preview.get("pacer_username") or "")
    return preview


def _parse_possible_json_text(value: Any) -> Dict[str, Any] | None:
    if isinstance(value, dict):
        return dict(value)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except Exception:
        return None
    return dict(parsed) if isinstance(parsed, dict) else None


def _normalize_courtlistener_court_reference(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = re.search(r"/courts/(?P<court_id>[^/]+)/?$", text)
    if match:
        return str(match.group("court_id") or "").strip()
    return text


def _resolve_packaged_courtlistener_fetch_context(minimal_view: Mapping[str, Any]) -> Dict[str, Any]:
    documents = [
        dict(item)
        for item in list(minimal_view.get("documents") or [])
        if isinstance(item, dict)
    ]
    summary_document = next(
        (
            item
            for item in documents
            if (
                str(item.get("document_type") or "") == "courtlistener_docket_summary"
                or str(dict(item.get("metadata") or {}).get("document_type") or "") == "courtlistener_docket_summary"
                or str(item.get("title") or "").strip().lower() == "courtlistener docket summary"
            )
        ),
        {},
    )
    summary_metadata = dict(summary_document.get("metadata") or {})
    raw_summary = dict(summary_metadata.get("raw") or {})
    original_summary_raw = dict(
        dict(raw_summary.get("metadata") or {}).get("raw") or {}
    )
    summary_source_url = str(
        summary_document.get("source_url")
        or raw_summary.get("source_url")
        or ""
    ).strip()
    return {
        "docket_id": str(minimal_view.get("docket_id") or ""),
        "case_name": str(minimal_view.get("case_name") or ""),
        "court": _normalize_courtlistener_court_reference(
            raw_summary.get("court")
            or original_summary_raw.get("court")
            or raw_summary.get("court_id")
            or original_summary_raw.get("court_id")
            or minimal_view.get("court")
            or ""
        ),
        "court_name": str(
            raw_summary.get("court_name")
            or original_summary_raw.get("court_name")
            or raw_summary.get("court_full_name")
            or original_summary_raw.get("court_full_name")
            or ""
        ).strip(),
        "docket_number": str(
            raw_summary.get("docket_number")
            or original_summary_raw.get("docket_number")
            or raw_summary.get("docketNumber")
            or original_summary_raw.get("docketNumber")
            or summary_document.get("document_number")
            or ""
        ).strip(),
        "pacer_case_id": str(
            raw_summary.get("pacer_case_id")
            or original_summary_raw.get("pacer_case_id")
            or raw_summary.get("pacerCaseId")
            or original_summary_raw.get("pacerCaseId")
            or ""
        ).strip(),
        "courtlistener_docket_id": str(
            minimal_view.get("docket_id")
            or raw_summary.get("id")
            or original_summary_raw.get("id")
            or ""
        ).strip(),
        "courtlistener_docket_url": str(
            summary_source_url
            or (minimal_view.get("package_manifest") or {}).get("source_url")
            or raw_summary.get("absolute_url")
            or original_summary_raw.get("absolute_url")
            or (minimal_view.get("package_manifest") or {}).get("source_path")
            or ""
        ).strip(),
    }


def _fetch_rendered_courtlistener_docket_summary(url: str) -> Dict[str, Any]:
    return asyncio.run(_fetch_rendered_courtlistener_docket_summary_async(url))


def _fetch_acquisition_target(
    url: str,
    *,
    request_timeout_seconds: float = 30.0,
    requests_module: Any | None = None,
) -> Dict[str, Any]:
    if requests_module is None:
        try:
            import requests as requests_module
        except ImportError as exc:  # pragma: no cover
            raise CourtListenerIngestionError("requests is required for acquisition target fetches.") from exc

    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests_module.get(url, headers=headers, timeout=request_timeout_seconds, allow_redirects=True)
    except Exception as exc:
        message = str(exc or "")
        lowered = message.lower()
        status = "network_error"
        if (
            "missingheaderbodyseparatordefect" in lowered
            or "failed to parse headers" in lowered
            or "404 ok" in lowered
        ):
            status = "upstream_gateway_error"
        return {
            "status": status,
            "final_url": url,
            "error": message,
        }
    status_code = int(getattr(response, "status_code", 0) or 0)
    final_url = str(getattr(response, "url", url) or url)
    content_type = str(getattr(response, "headers", {}).get("Content-Type") or "").lower()
    content = bytes(getattr(response, "content", b"") or b"")
    text = str(getattr(response, "text", "") or "")

    if status_code >= 400:
        return {
            "status": "http_error",
            "status_code": status_code,
            "final_url": final_url,
            "content_type": content_type,
        }

    if "application/pdf" in content_type or content.startswith(b"%PDF"):
        extracted_text = _extract_text_from_pdf_bytes_direct(content)
        extraction_method = "pdf_text"
        if not _looks_like_useful_text(extracted_text):
            ocr_text = _extract_text_from_pdf_bytes_ocr(content)
            if _looks_like_useful_text(ocr_text):
                extracted_text = ocr_text
                extraction_method = "pdf_ocr"
        return {
            "status": "fetched",
            "status_code": status_code,
            "final_url": final_url,
            "content_type": content_type or "application/pdf",
            "byte_count": len(content),
            "text_length": len(extracted_text or ""),
            "extraction_method": extraction_method,
            "text_preview": str(extracted_text or "")[:1200],
        }

    normalized_text = " ".join(text.split())
    lowered = normalized_text.lower()
    if any(marker in lowered for marker in ["pacer login", "login to manage your account", "username", "password"]) and "pacer" in lowered:
        return {
            "status": "authentication_required",
            "status_code": status_code,
            "final_url": final_url,
            "content_type": content_type or "text/html",
            "text_preview": normalized_text[:1200],
        }

    return {
        "status": "html_only",
        "status_code": status_code,
        "final_url": final_url,
        "content_type": content_type or "text/html",
        "text_preview": normalized_text[:1200],
    }


def _fetch_public_pdf_text(
    url: str,
    *,
    request_timeout_seconds: float = 30.0,
    requests_module: Any | None = None,
) -> Dict[str, Any]:
    if requests_module is None:
        try:
            import requests as requests_module
        except ImportError as exc:  # pragma: no cover
            raise CourtListenerIngestionError("requests is required for CourtListener public PDF fetches.") from exc

    response = requests_module.get(url, timeout=request_timeout_seconds, headers={"User-Agent": "Mozilla/5.0"})
    pdf_bytes = bytes(getattr(response, "content", b"") or b"")
    direct_text = _extract_text_from_pdf_bytes_direct(pdf_bytes)
    extraction_method = "pdf_text"
    text_value = direct_text
    if not _looks_like_useful_text(text_value):
        ocr_text = _extract_text_from_pdf_bytes_ocr(pdf_bytes)
        if _looks_like_useful_text(ocr_text):
            text_value = ocr_text
            extraction_method = "pdf_ocr"
    return {
        "url": url,
        "status_code": int(getattr(response, "status_code", 0) or 0),
        "byte_count": len(pdf_bytes),
        "text_length": len(text_value or ""),
        "extraction_method": extraction_method,
        "text": str(text_value or ""),
        "text_preview": str(text_value or "")[:1200],
    }


def _classify_pacer_browser_state(
    *,
    current_url: str,
    body_text: str,
    has_login_fields: bool,
    has_mfa_submit: bool,
    has_redaction_continue: bool,
    download_count: int,
) -> str:
    lowered = str(body_text or "").lower()
    current = str(current_url or "").lower()
    if download_count > 0:
        return "downloaded_pdf"
    if "account update required" in lowered or "current account access has been restricted" in lowered:
        return "account_update_required"
    if has_mfa_submit or "one-time passcode" in lowered or "multifactor" in lowered or "multi-factor" in lowered:
        return "mfa_required"
    if has_redaction_continue:
        return "redaction_confirmation_required"
    if has_login_fields or "pacer: login" in lowered or "log in to pacer systems" in lowered or "login.jsf" in current:
        return "authentication_required"
    return "unknown"


async def _fetch_pacer_document_with_browser_async(
    target_url: str,
    *,
    pacer_username: str | None = None,
    pacer_password: str | None = None,
    pacer_client_code: str | None = None,
    request_timeout_seconds: float = 30.0,
) -> Dict[str, Any]:
    try:
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        from playwright.async_api import async_playwright
    except Exception as exc:  # pragma: no cover
        raise CourtListenerIngestionError("Playwright is required for browser-authenticated PACER fetches.") from exc

    resolved_username = resolve_pacer_username(pacer_username)
    resolved_password = resolve_pacer_password(pacer_password)
    resolved_client_code = resolve_pacer_client_code(pacer_client_code)
    if not resolved_username or not resolved_password:
        raise CourtListenerIngestionError("PACER username and password are required for browser-authenticated PACER fetches.")

    user_agent = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    timeout_ms = max(1000, int(float(request_timeout_seconds or 30.0) * 1000))
    downloads: List[Any] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(
                user_agent=user_agent,
                viewport={"width": 1400, "height": 1000},
                locale="en-US",
                accept_downloads=True,
            )
            page = await context.new_page()
            page.on("download", lambda download: downloads.append(download))

            await page.goto(target_url, wait_until="domcontentloaded", timeout=timeout_ms)
            await page.wait_for_timeout(1500)

            if await page.locator("#loginForm\\:loginName").count():
                await page.locator("#loginForm\\:loginName").fill(resolved_username)
            if await page.locator("#loginForm\\:password").count():
                await page.locator("#loginForm\\:password").fill(resolved_password)
            if resolved_client_code and await page.locator("#loginForm\\:clientCode").count():
                await page.locator("#loginForm\\:clientCode").fill(resolved_client_code)
            if await page.locator("#regmsg\\:chkRedact_input").count() and await page.locator("#regmsg\\:chkRedact_input").is_visible():
                try:
                    await page.locator("#regmsg\\:chkRedact_input").check()
                except Exception:
                    pass
            if await page.locator("#loginForm\\:fbtnLogin").count():
                try:
                    await page.locator("#loginForm\\:fbtnLogin").click(no_wait_after=True, timeout=min(timeout_ms, 5000))
                except PlaywrightTimeoutError:
                    pass

            for _ in range(6):
                await page.wait_for_timeout(1000)
                if await page.locator("#regmsg\\:bpmConfirm").count() and await page.locator("#regmsg\\:bpmConfirm").is_visible():
                    try:
                        await page.locator("#regmsg\\:bpmConfirm").click(no_wait_after=True, timeout=3000)
                    except PlaywrightTimeoutError:
                        pass
                if downloads:
                    break

            body_text = await page.locator("body").inner_text()
            has_login_fields = bool(await page.locator("#loginForm\\:loginName").count())
            has_mfa_submit = bool(await page.locator("#mfaForm\\:btnOk").count())
            has_redaction_continue = bool(await page.locator("#regmsg\\:bpmConfirm").count())
            status = _classify_pacer_browser_state(
                current_url=page.url,
                body_text=body_text,
                has_login_fields=has_login_fields,
                has_mfa_submit=has_mfa_submit,
                has_redaction_continue=has_redaction_continue,
                download_count=len(downloads),
            )

            result: Dict[str, Any] = {
                "status": status,
                "target_url": target_url,
                "final_url": page.url,
                "title": await page.title(),
                "body_preview": body_text[:1600],
            }

            if downloads:
                download = downloads[0]
                suggested_name = str(await download.suggested_filename())
                temp_path = Path("/tmp") / f"pacer_download_{int(time.time() * 1000)}_{suggested_name}"
                await download.save_as(str(temp_path))
                pdf_bytes = temp_path.read_bytes()
                extracted_text = _extract_text_from_pdf_bytes_direct(pdf_bytes)
                extraction_method = "pdf_text"
                if not _looks_like_useful_text(extracted_text):
                    ocr_text = _extract_text_from_pdf_bytes_ocr(pdf_bytes)
                    if _looks_like_useful_text(ocr_text):
                        extracted_text = ocr_text
                        extraction_method = "pdf_ocr"
                result.update(
                    {
                        "status": "downloaded_pdf",
                        "download_path": str(temp_path),
                        "download_filename": suggested_name,
                        "byte_count": len(pdf_bytes),
                        "text_length": len(extracted_text or ""),
                        "extraction_method": extraction_method,
                        "text_preview": str(extracted_text or "")[:1200],
                    }
                )
            return result
        finally:
            await browser.close()


def probe_courtlistener_document_acquisition_target(url: str) -> Dict[str, Any]:
    return asyncio.run(_probe_courtlistener_document_acquisition_target_async(url))


async def _probe_courtlistener_public_filing_pdfs_async(url: str) -> Dict[str, Any]:
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:  # pragma: no cover
        raise CourtListenerIngestionError("Playwright is required for CourtListener public filing PDF probing.") from exc

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
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)
            links: List[Dict[str, str]] = []
            seen_hrefs: set[str] = set()
            locator = page.locator("a")
            count = min(await locator.count(), 250)
            for index in range(count):
                link = locator.nth(index)
                text = str((await link.text_content()) or "").strip()
                href = str((await link.get_attribute("href")) or "").strip()
                absolute_href = urljoin(page.url, href) if href else ""
                if (
                    absolute_href.lower().endswith(".pdf")
                    and "storage.courtlistener.com" in absolute_href.lower()
                    and absolute_href not in seen_hrefs
                ):
                    seen_hrefs.add(absolute_href)
                    links.append({"text": text, "href": absolute_href})
            return {
                "status": "success",
                "url": page.url,
                "title": await page.title(),
                "pdf_links": links,
                "body_preview": (await page.locator("body").inner_text())[:1200],
            }
        finally:
            await browser.close()


async def _probe_courtlistener_document_acquisition_target_async(url: str) -> Dict[str, Any]:
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:  # pragma: no cover
        raise CourtListenerIngestionError("Playwright is required for CourtListener document acquisition probing.") from exc

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
            await page.wait_for_timeout(2000)
            links: List[Dict[str, str]] = []
            locator = page.locator("a")
            count = min(await locator.count(), 250)
            for index in range(count):
                link = locator.nth(index)
                text = str((await link.text_content()) or "").strip()
                href = str((await link.get_attribute("href")) or "").strip()
                if text or href:
                    links.append({"text": text, "href": href})
            summary = _summarize_rendered_courtlistener_document_links(
                links,
                url=page.url,
                title=await page.title(),
            )
            body_text = await page.locator("body").inner_text()
            summary["contains_pacer"] = "PACER" in body_text
            summary["contains_recap"] = "RECAP" in body_text
            summary["body_text_preview"] = body_text[:1200]
            return summary
        finally:
            await browser.close()


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


def _summarize_rendered_courtlistener_document_links(
    links: Iterable[Mapping[str, Any]],
    *,
    url: str,
    title: str = "",
) -> Dict[str, Any]:
    pacer_purchase_url = ""
    download_url = ""
    matching_links: List[Dict[str, str]] = []
    for item in links:
        text = str(item.get("text") or "").strip()
        href = str(item.get("href") or "").strip()
        absolute_href = urljoin(url, href) if href else ""
        haystack = f"{text} {absolute_href}".lower()
        if "buy on pacer" in haystack or "ecf." in haystack:
            matching_links.append({"text": text, "href": absolute_href})
            if not pacer_purchase_url and absolute_href:
                pacer_purchase_url = absolute_href
        elif "download" in haystack and absolute_href:
            matching_links.append({"text": text, "href": absolute_href})
            if not download_url:
                download_url = absolute_href
        elif "recap" in haystack and absolute_href:
            matching_links.append({"text": text, "href": absolute_href})
    return {
        "status": "success",
        "url": url,
        "title": str(title or ""),
        "pacer_purchase_url": pacer_purchase_url,
        "download_url": download_url,
        "matching_links": matching_links[:20],
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


def _post_json(
    url: str,
    *,
    headers: Dict[str, str],
    json_payload: Mapping[str, Any],
    requests_module: Any,
    request_timeout_seconds: float = 30.0,
) -> Dict[str, Any]:
    merged_headers = {"Content-Type": "application/json", **dict(headers or {})}
    response = requests_module.post(
        url,
        headers=merged_headers,
        json=dict(json_payload or {}),
        timeout=max(1.0, float(request_timeout_seconds or 30.0)),
    )
    status_code = int(getattr(response, "status_code", 0) or 0)
    if status_code not in {200, 201, 202}:
        body = ""
        try:
            body = str(getattr(response, "text", "") or "")[:500]
        except Exception:
            body = ""
        raise CourtListenerIngestionError(f"CourtListener POST failed ({status_code}) for {url}: {body}")
    data = response.json()
    if not isinstance(data, dict):
        raise CourtListenerIngestionError(f"Expected JSON object from CourtListener POST for {url}")
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
