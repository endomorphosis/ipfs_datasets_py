"""Bounded live acquisition for Tennessee's delegated Lexis catalog.

This module owns the browser-only seam.  It retains the rendered container
and every exact ``PATCH`` response before returning any parsed catalog data;
the Tennessee scraper subsequently reparses the same bytes from its ledger.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit

from ipfs_datasets_py.utils import anyio_compat as asyncio

from .tennessee_lexis import (
    PUBLIC_CONTAINER_URL,
    PUBLIC_ENTRY_URL,
    TOC_ENDPOINT_URL,
    TennesseeLexisNode,
    canonical_toc_patch_request,
    container_url_matches,
    derive_exact_metadata_frontier,
    parse_root_html,
    parse_title_subtree_payload,
)

GET_ACCEPT = "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5"
PATCH_ACCEPT = "application/json, text/javascript, */*; q=0.01"
PHASE_SCHEMA = "tennessee-lexis-acquisition-phase-v1"
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


def _phase_fields(
    acquisition_phase_id: str | None,
    acquisition_phase_started_at: str | None,
) -> dict[str, str]:
    if acquisition_phase_id is None and acquisition_phase_started_at is None:
        return {}
    phase_id = str(acquisition_phase_id or "").strip().lower()
    started_at = str(acquisition_phase_started_at or "").strip()
    if not _SHA256_RE.fullmatch(phase_id) or not started_at:
        raise ValueError("Tennessee acquisition phase identity is incomplete")
    try:
        parsed = datetime.fromisoformat(started_at)
    except ValueError as exc:
        raise ValueError("Tennessee acquisition phase start is not ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Tennessee acquisition phase start requires a timezone")
    return {
        "acquisition_phase_id": phase_id,
        "acquisition_phase_schema": PHASE_SCHEMA,
        "acquisition_phase_started_at": parsed.astimezone(UTC).isoformat(),
    }


def canonical_rendered_root_request(
    *,
    acquisition_phase_id: str | None = None,
    acquisition_phase_started_at: str | None = None,
) -> dict[str, Any]:
    """Return the stable rendered-container GET identity used by the ledger."""

    return {
        **_phase_fields(acquisition_phase_id, acquisition_phase_started_at),
        "headers": {"Accept": GET_ACCEPT},
        "method": "GET",
        "rendered_by": "playwright",
        "url": PUBLIC_CONTAINER_URL,
        "wait_until": "domcontentloaded",
    }


def canonical_live_toc_patch_request(
    node: TennesseeLexisNode,
    *,
    acquisition_phase_id: str,
    acquisition_phase_started_at: str,
    session_request_id_sha256: str,
) -> tuple[str, bytes, dict[str, Any]]:
    """Bind one exact PATCH body to its phase and browser-session request ID."""

    endpoint, request_body, base_request = canonical_toc_patch_request(node)
    session_digest = str(session_request_id_sha256 or "").strip().lower()
    if not _SHA256_RE.fullmatch(session_digest):
        raise ValueError("Tennessee PATCH requires a sanitized session request ID")
    request = {
        **base_request,
        **_phase_fields(acquisition_phase_id, acquisition_phase_started_at),
        "headers": {
            "Accept": PATCH_ACCEPT,
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
        },
        "session_request_header": "X-LN-CurrentRequestId",
        "session_request_id_sha256": session_digest,
    }
    return endpoint, request_body, request


def _sanitize_browser_url(value: str) -> dict[str, str]:
    """Remove session values while retaining a digest of the exact locator."""

    raw = str(value or "").strip()
    parsed = urlsplit(raw)
    safe_query = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if key.casefold() not in {"crid", "prid"}
    ]
    safe_url = urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(safe_query), "")
    )
    return {
        "url": safe_url,
        "url_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
    }


def _session_request_identity(value: str) -> tuple[str, str]:
    query = parse_qs(urlsplit(str(value or "")).query, keep_blank_values=True)
    values = query.get("crid") or []
    if len(values) != 1 or not re.fullmatch(r"[A-Za-z0-9-]{1,128}", values[0]):
        raise RuntimeError(
            "Tennessee rendered container omitted its bounded session request ID"
        )
    request_id = values[0]
    return request_id, hashlib.sha256(request_id.encode("utf-8")).hexdigest()


def _redirect_chain(navigation: Any) -> list[dict[str, str]]:
    request = getattr(navigation, "request", None)
    chain: list[str] = []
    while request is not None:
        chain.append(str(getattr(request, "url", "") or ""))
        request = getattr(request, "redirected_from", None)
    return [_sanitize_browser_url(url) for url in reversed(chain) if url]


def _playwright_manager() -> Any:
    """Load Playwright lazily; tests replace this boundary hermetically."""

    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            f"Tennessee live catalog requires Playwright: {exc}"
        ) from exc
    return async_playwright()


def assert_rendered_root_coherence(
    *,
    retained_payload: bytes,
    live_payload: bytes,
    expected_titles: Sequence[tuple[str, str]],
) -> None:
    """Require a resumed browser session to expose the retained root semantics."""

    try:
        retained_roots, retained_tables = parse_root_html(
            bytes(retained_payload).decode("utf-8-sig", errors="strict"),
            expected_titles=expected_titles,
        )
        live_roots, live_tables = parse_root_html(
            bytes(live_payload).decode("utf-8-sig", errors="strict"),
            expected_titles=expected_titles,
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError(
            "Tennessee resumed browser root failed strict semantic validation"
        ) from exc
    if live_roots != retained_roots or live_tables != retained_tables:
        raise RuntimeError(
            "Tennessee resumed browser root changed retained catalog semantics"
        )


@dataclass(frozen=True)
class TennesseeLiveCatalog:
    """One retained and fully parsed root-plus-title catalog wave."""

    title_roots: tuple[TennesseeLexisNode, ...]
    tables_root: TennesseeLexisNode
    subtrees_by_root_id: Mapping[str, tuple[TennesseeLexisNode, ...]]
    metadata: Mapping[str, Any]
    observed_at: str
    network_patch_count: int
    retained_patch_count: int


@dataclass(frozen=True)
class TennesseeRetainedBrowserInput:
    """Replay bytes plus sanitized response-bound browser proof."""

    body: bytes
    response_proof: Mapping[str, Any]


def _retained_browser_input(
    value: Any,
) -> TennesseeRetainedBrowserInput | None:
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray, memoryview)):
        payload = bytes(value)
        return (
            TennesseeRetainedBrowserInput(body=payload, response_proof={})
            if payload
            else None
        )
    if isinstance(value, TennesseeRetainedBrowserInput):
        if not value.body:
            return None
        return value
    raise RuntimeError("Tennessee retained replay returned a non-byte payload")


async def _patch_with_retries(
    page: Any,
    *,
    endpoint: str,
    request_body: bytes,
    session_request_id: str,
    retry_count: int,
) -> tuple[bytes, Mapping[str, Any], str]:
    last_error = "missing response"
    for attempt in range(retry_count):
        result = await page.evaluate(
            """
            async ({endpoint, requestBody, sessionRequestId}) => {
              const headers = {
                'Accept': 'application/json, text/javascript, */*; q=0.01',
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
              };
              if (sessionRequestId) {
                headers['X-LN-CurrentRequestId'] = sessionRequestId;
              }
              const response = await fetch(endpoint, {
                method: 'PATCH', credentials: 'same-origin', headers,
                body: requestBody
              });
              const text = await response.text();
              return {
                status: response.status,
                contentType: response.headers.get('content-type') || '',
                finalUrl: response.url || '',
                redirected: response.redirected === true,
                text
              };
            }
            """,
            {
                "endpoint": endpoint,
                "requestBody": request_body.decode("utf-8", errors="strict"),
                "sessionRequestId": session_request_id,
            },
        )
        # The source page owns its JavaScript realm and can replace ``Date``.
        # Timestamp the completed response at the verifier boundary instead.
        response_observed_at = datetime.now(UTC).isoformat()
        if isinstance(result, Mapping):
            status = int(result.get("status") or 0)
            content_type = str(result.get("contentType") or "").casefold()
            response = str(result.get("text") or "").encode("utf-8")
            final_url = str(result.get("finalUrl") or "").strip()
            redirected = result.get("redirected") is True
            if (
                status == 200
                and "json" in content_type
                and response
                and final_url == endpoint
                and not redirected
            ):
                return (
                    response,
                    {
                        "final_url": final_url,
                        "redirect_chain": [],
                        "redirected": False,
                        "response_observed_at": response_observed_at,
                        "session_request_id_sha256": hashlib.sha256(
                            session_request_id.encode("utf-8")
                        ).hexdigest(),
                    },
                    "",
                )
            last_error = f"HTTP {status or 'missing'}"
            if status == 200:
                last_error += " with invalid JSON/final-URL/redirect proof"
        if attempt + 1 < retry_count:
            await asyncio.sleep(min(1.0, 0.15 * (attempt + 1)))
    return b"", {}, last_error


async def acquire_live_catalog(
    *,
    acquisition_phase_id: str,
    acquisition_phase_started_at: str,
    expected_titles: Sequence[tuple[str, str]],
    expected_patch_count: int,
    retain_parser_input: Callable[..., Any],
    replay_parser_input: Callable[[str, Mapping[str, Any]], bytes | None],
    retries: int = 2,
    timeout_ms: int = 60_000,
) -> TennesseeLiveCatalog:
    """Acquire only missing rendered-root/PATCH identities, then parse them.

    Successful responses are synchronously admitted through
    ``retain_parser_input`` before this function parses their bytes.  On a
    restart, exact ledger hits are reused and only missing PATCH identities
    are submitted.  A browser navigation may still be needed to establish a
    Lexis session for missing PATCH requests; it is not admitted as a second
    parser input when the canonical rendered root already exists.
    """

    if not callable(retain_parser_input) or not callable(replay_parser_input):
        raise TypeError("Tennessee live catalog requires retention and replay seams")
    retry_count = max(1, min(int(retries), 5))
    timeout = max(5_000, min(int(timeout_ms), 120_000))
    phase_fields = _phase_fields(
        acquisition_phase_id,
        acquisition_phase_started_at,
    )
    root_request = canonical_rendered_root_request(
        acquisition_phase_id=phase_fields["acquisition_phase_id"],
        acquisition_phase_started_at=phase_fields["acquisition_phase_started_at"],
    )
    root_retained = _retained_browser_input(
        replay_parser_input(PUBLIC_CONTAINER_URL, root_request)
    )
    root_payload = root_retained.body if root_retained is not None else None
    retained_root_proof = (
        dict(root_retained.response_proof) if root_retained is not None else {}
    )
    retained_session_digest = (
        str(retained_root_proof.get("session_request_id_sha256") or "").strip().lower()
    )
    if retained_root_proof and not _SHA256_RE.fullmatch(retained_session_digest):
        raise RuntimeError(
            "Tennessee retained root omitted its sanitized browser session proof"
        )
    page: Any = None
    browser: Any = None
    browser_manager: Any = None
    live_session_id = ""
    live_session_digest = ""
    latest_root_proof = dict(retained_root_proof)
    live_patch_proofs: dict[int, Mapping[str, Any]] = {}

    async def _open_browser() -> Any:
        nonlocal browser, browser_manager, page, root_payload
        nonlocal latest_root_proof, live_session_digest, live_session_id
        nonlocal retained_session_digest
        if page is not None:
            return page
        browser_manager = _playwright_manager()
        playwright = await browser_manager.__aenter__()
        browser = await playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        )
        context = await browser.new_context(
            extra_http_headers={"Accept": GET_ACCEPT},
            locale="en-US",
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()
        navigation = await page.goto(
            PUBLIC_CONTAINER_URL,
            wait_until="domcontentloaded",
            timeout=timeout,
            referer=PUBLIC_ENTRY_URL,
        )
        await page.wait_for_selector("li.js-node", timeout=min(timeout, 30_000))
        live_page_url = str(page.url or "")
        if not container_url_matches(live_page_url):
            raise RuntimeError(
                "Tennessee browser escaped the delegated container config"
            )
        session_request_id, session_digest = _session_request_identity(live_page_url)
        status = int(getattr(navigation, "status", 0) or 0)
        rendered = str(await page.content() or "").encode("utf-8")
        root_observed_at = datetime.now(UTC).isoformat()
        if status != 200 or not rendered:
            raise RuntimeError(
                f"Tennessee rendered root returned HTTP {status or 'unknown'}"
            )
        final_proof = _sanitize_browser_url(live_page_url)
        latest_root_proof = {
            "final_url": final_proof["url"],
            "final_url_sha256": final_proof["url_sha256"],
            "redirect_chain": _redirect_chain(navigation),
            "redirected": bool(
                getattr(navigation, "request", None)
                and getattr(navigation.request, "redirected_from", None)
            ),
            "response_observed_at": root_observed_at,
            "session_request_id_sha256": session_digest,
        }
        if root_payload is not None:
            assert_rendered_root_coherence(
                retained_payload=root_payload,
                live_payload=rendered,
                expected_titles=expected_titles,
            )
        # Retain every actual navigation boundary.  A resumed, semantically
        # coherent root is current authority for its new session-bound PATCH
        # plan even when the parser continues to consume the original bytes.
        retain_parser_input(
            body=rendered,
            media_type="text/html",
            observed_at=root_observed_at,
            official_url=PUBLIC_CONTAINER_URL,
            response_proof=latest_root_proof,
            response_status=status,
            sanitized_request=root_request,
        )
        if root_payload is None:
            # Retention is the parser-admission boundary.
            root_payload = rendered
            retained_session_digest = session_digest
        live_session_id = session_request_id
        live_session_digest = session_digest
        return page

    try:
        if root_payload is None:
            await _open_browser()
        if not root_payload:
            raise RuntimeError("Tennessee rendered root retention returned no bytes")
        title_roots, tables_root = parse_root_html(
            root_payload.decode("utf-8-sig", errors="strict"),
            expected_titles=expected_titles,
        )
        expandable = [
            node for node in title_roots if node.can_expand or node.has_children
        ]
        if len(expandable) != int(expected_patch_count):
            raise RuntimeError(
                "Tennessee rendered root changed expandable title membership: "
                f"expected {expected_patch_count}, observed {len(expandable)}"
            )
        if retained_session_digest:
            patch_specs = [
                canonical_live_toc_patch_request(
                    node,
                    acquisition_phase_id=phase_fields["acquisition_phase_id"],
                    acquisition_phase_started_at=phase_fields[
                        "acquisition_phase_started_at"
                    ],
                    session_request_id_sha256=retained_session_digest,
                )
                for node in expandable
            ]
            patch_retained = [
                _retained_browser_input(replay_parser_input(endpoint, request))
                for endpoint, _body, request in patch_specs
            ]
        else:
            # Compatibility-only unphased fixtures can still prove parser
            # behavior, but production always carries root response proof.
            patch_specs = [canonical_toc_patch_request(node) for node in expandable]
            patch_retained = [
                _retained_browser_input(replay_parser_input(endpoint, request))
                for endpoint, _body, request in patch_specs
            ]
        patch_payloads: list[bytes | None] = [
            item.body if item is not None else None for item in patch_retained
        ]
        missing_positions = [
            position
            for position, payload in enumerate(patch_payloads)
            if payload is None
        ]
        if missing_positions:
            live_page = await _open_browser()
            # A resumed navigation commonly receives a new session request ID.
            # Rebuild the whole PATCH plan under that identity and reuse only
            # exact same-session hits; never mix an old canonical request with
            # a different wire request.
            patch_specs = [
                canonical_live_toc_patch_request(
                    node,
                    acquisition_phase_id=phase_fields["acquisition_phase_id"],
                    acquisition_phase_started_at=phase_fields[
                        "acquisition_phase_started_at"
                    ],
                    session_request_id_sha256=live_session_digest,
                )
                for node in expandable
            ]
            patch_retained = [
                _retained_browser_input(replay_parser_input(endpoint, request))
                for endpoint, _body, request in patch_specs
            ]
            patch_payloads = [
                item.body if item is not None else None for item in patch_retained
            ]
            missing_positions = [
                position
                for position, payload in enumerate(patch_payloads)
                if payload is None
            ]
            for position in missing_positions:
                endpoint, request_body, sanitized_request = patch_specs[position]
                if endpoint != TOC_ENDPOINT_URL:
                    raise RuntimeError(
                        "Tennessee PATCH target escaped the delegated TOC"
                    )
                response, response_proof, error = await _patch_with_retries(
                    live_page,
                    endpoint=endpoint,
                    request_body=request_body,
                    session_request_id=live_session_id,
                    retry_count=retry_count,
                )
                if error or not response:
                    raise RuntimeError(
                        "Tennessee deepest title TOC wave failed at source position "
                        f"{position}: {error or 'missing response'}"
                    )
                retain_parser_input(
                    body=response,
                    media_type="application/json",
                    observed_at=str(response_proof["response_observed_at"]),
                    official_url=endpoint,
                    response_proof=response_proof,
                    response_status=200,
                    sanitized_request=sanitized_request,
                )
                patch_payloads[position] = response
                live_patch_proofs[position] = dict(response_proof)

        # No PATCH body is parsed until the complete bounded wave has crossed
        # the synchronous retention boundary above.
        subtrees: dict[str, tuple[TennesseeLexisNode, ...]] = {}
        for parent, _spec, raw_payload in zip(
            expandable,
            patch_specs,
            patch_payloads,
            strict=True,
        ):
            if not raw_payload:
                raise RuntimeError("Tennessee retained PATCH wave is incomplete")
            try:
                response = json.loads(raw_payload.decode("utf-8-sig", errors="strict"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise RuntimeError(
                    f"Tennessee Title {parent.title_number} TOC is invalid JSON"
                ) from exc
            descendants, _closed_ids, error = parse_title_subtree_payload(
                response,
                parent=parent,
                target_level=max(parent.open_to_levels),
            )
            if error:
                raise RuntimeError(
                    f"Tennessee Title {parent.title_number} TOC did not close: {error}"
                )
            subtrees[parent.node_id] = tuple(descendants)
        metadata = derive_exact_metadata_frontier(
            title_roots,
            subtrees_by_root_id=subtrees,
        )
        observed_values = [
            str(
                item.response_proof.get("response_observed_at")
                if item is not None
                else ""
            ).strip()
            for item in patch_retained
        ]
        observed_values.extend(
            str(item.get("response_observed_at") or "").strip()
            for item in live_patch_proofs.values()
        )
        observed_values.append(
            str(latest_root_proof.get("response_observed_at") or "").strip()
        )
        observed_values = [item for item in observed_values if item]
        return TennesseeLiveCatalog(
            title_roots=tuple(title_roots),
            tables_root=tables_root,
            subtrees_by_root_id=subtrees,
            metadata=metadata,
            observed_at=max(observed_values) if observed_values else "",
            network_patch_count=len(missing_positions),
            retained_patch_count=len(patch_specs) - len(missing_positions),
        )
    finally:
        if browser is not None:
            await browser.close()
        if browser_manager is not None:
            await browser_manager.__aexit__(None, None, None)


__all__ = [
    "GET_ACCEPT",
    "PATCH_ACCEPT",
    "PHASE_SCHEMA",
    "TennesseeLiveCatalog",
    "TennesseeRetainedBrowserInput",
    "acquire_live_catalog",
    "assert_rendered_root_coherence",
    "canonical_live_toc_patch_request",
    "canonical_rendered_root_request",
]
