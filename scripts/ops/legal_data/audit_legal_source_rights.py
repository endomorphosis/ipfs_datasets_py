#!/usr/bin/env python3
"""Fail-closed LCR-082/LCR-078 source-rights audit, fixture builder, and live sealer.

The validation modes accept no catalog, schema, registry, clock, freshness, or
output-path override.  ``--emit-deterministic-fixture`` only prints the exact
checked-in fixture candidate to stdout; it never writes repository or remote
state.  Normal ``--fixture-only --check`` compares the committed catalog with
that deterministic candidate before evaluation.  Live mode observes terms and
robots for the complete LCR-002/LCR-048 frontier; ``--seal`` writes the live
catalog and compliance receipt, and ``--require-live-source-evidence --check``
authorizes only a current, complete, secret-free live catalog plus receipt.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.legal_source_rights_policy import (
    ADMISSIBLE_CONTENT_SCOPES,
    CATALOG_PRODUCER,
    CATALOG_SCHEMA_VERSION,
    CONDITION_EVIDENCE_SCHEMA_VERSION,
    CURRENTNESS_DISCLAIMER,
    EVIDENCE_SCHEMA_VERSION,
    EXPECTED_FRONTIER_SIZE,
    FIXTURE_GOAL_ID,
    FIXTURE_TASK_ID,
    LIVE_GOAL_ID,
    LIVE_TASK_ID,
    PROGRAM_ID,
    SCHEMA_VERSION,
    TARGET_DATASET_REPO_IDS,
    VERIFIER_ID,
    CatalogSchemaError,
    ContentScope,
    LegalSourceRightsPolicyError,
    audit_fixture_catalog,
    compute_artifact_digests,
    default_live_catalog_path,
    derive_expected_scope_frontier,
    format_utc_timestamp,
    frontier_digest_sha256,
    load_catalog_snapshot,
    load_spdx_registry,
    require_live_source_evidence,
    sha256_json,
)


REPORT_SCHEMA = "ipfs_datasets_py/legal-source-rights-compliance@2"
CODE_VERSION = "2"
LIVE_CATALOG_RELATIVE = Path("data/legal/legal_source_rights_catalog.json")
COMPLIANCE_RELATIVE = Path("docs/reports/legal_corpora_reindex/legal_source_rights_compliance.json")
LIVE_USER_AGENT = "legal-corpora-reindex-v1-source-rights-auditor/2"
LIVE_FETCH_TIMEOUT_SECONDS = 20.0
LIVE_FETCH_RETRIES = 2
LIVE_FETCH_WORKERS = 8
LIVE_MAX_BODY_BYTES = 131072
_HOME_PATH_RE = re.compile(r"/home/[A-Za-z0-9._-]+")
_TOKEN_RE = re.compile(
    r"(?:hf_[A-Za-z0-9]{16,}|sk-[A-Za-z0-9]{16,}|Bearer\s+[A-Za-z0-9\-._~+/]+=*)"
)


class AuditError(RuntimeError):
    pass


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _base64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _identity_fields(mode: str) -> dict[str, str]:
    if mode == "fixture":
        return {
            "producer": CATALOG_PRODUCER,
            "program_id": PROGRAM_ID,
            "task_id": FIXTURE_TASK_ID,
            "goal_id": FIXTURE_GOAL_ID,
            "evidence_mode": "fixture",
        }
    if mode == "live":
        return {
            "producer": CATALOG_PRODUCER,
            "program_id": PROGRAM_ID,
            "task_id": LIVE_TASK_ID,
            "goal_id": LIVE_GOAL_ID,
            "evidence_mode": "live",
        }
    raise ValueError("evidence mode must be exactly fixture or live")


def default_compliance_path() -> Path:
    return REPOSITORY_ROOT / COMPLIANCE_RELATIVE


def _evidence(
    *,
    kind: str,
    source_id: str,
    content_scope: str,
    url: str,
    observed_at: str,
    content: bytes,
    mode: str = "fixture",
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "evidence_kind": kind,
        **_identity_fields(mode),
        "verifier_id": VERIFIER_ID,
        "source_id": source_id,
        "content_scope": content_scope,
        "url": url,
        "verifier_observed_at": observed_at,
        "content_bytes_base64": _base64(content),
        "content_sha256": _sha256(content),
    }
    body["evidence_digest_sha256"] = sha256_json(body)
    return body


def _condition_receipt(
    *,
    condition_id: str,
    source_id: str,
    content_scope: str,
    observed_at: str,
    request: bytes,
    response: bytes,
    mode: str = "fixture",
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema_version": CONDITION_EVIDENCE_SCHEMA_VERSION,
        **_identity_fields(mode),
        "verifier_id": VERIFIER_ID,
        "condition_id": condition_id,
        "source_id": source_id,
        "content_scope": content_scope,
        "verifier_observed_at": observed_at,
        "request_bytes_base64": _base64(request),
        "request_sha256": _sha256(request),
        "response_bytes_base64": _base64(response),
        "response_sha256": _sha256(response),
    }
    body["receipt_digest_sha256"] = sha256_json(body)
    return body


def _license_binding(scope: ContentScope) -> tuple[str, str, str]:
    if scope is ContentScope.STATUTORY_TEXT:
        return (
            "LicenseRef-US-State-Statutory-Text",
            "government_edicts_doctrine",
            "d48cb14da98ecaa1f06e2ba498b17cadd9f0adaea38ceb28d71759ed049c8508",
        )
    if scope is ContentScope.FEDERAL_GOVERNMENT_TEXT:
        return (
            "LicenseRef-US-Federal-Government-Work",
            "us_government_work",
            "46cbe5c99f7016f4f9ced6344bb297581c2a78dbc2bdd91e93b188a025484e1d",
        )
    if scope is ContentScope.ANNOTATIONS:
        return (
            "LicenseRef-Annotations-Reserved",
            "proprietary",
            "af79ff861db14427b987ea16dab361da37194d8eee69fc7e00ecb78073bcd610",
        )
    if scope is ContentScope.DATABASE_CONTENT:
        return (
            "LicenseRef-Database-Content-Reserved",
            "proprietary",
            "b6d3f8abf435c9ea6cc789adab780b03e88cb57169fee2a9e16a21aad9580bb9",
        )
    return (
        "LicenseRef-Site-Presentation-Reserved",
        "proprietary",
        "e445a14ae5519d72e26458c8ba81e080bb403fb2d45bd41bd2485fe6126b0da6",
    )


class LiveFetchResult:
    """Immutable live HTTP observation used by the catalog builder and tests."""

    __slots__ = (
        "fetch_url",
        "status",
        "body",
        "request_bytes",
        "response_bytes",
        "observed_at",
        "error",
        "notes",
    )

    def __init__(
        self,
        fetch_url: str,
        status: int,
        body: bytes,
        request_bytes: bytes,
        response_bytes: bytes,
        observed_at: str,
        error: str | None = None,
        notes: str | None = None,
    ) -> None:
        self.fetch_url = fetch_url
        self.status = status
        self.body = body
        self.request_bytes = request_bytes
        self.response_bytes = response_bytes
        self.observed_at = observed_at
        self.error = error
        self.notes = notes


LiveFetchFn = Callable[[str], LiveFetchResult]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _truncate_body(body: bytes) -> bytes:
    if len(body) <= LIVE_MAX_BODY_BYTES:
        return body
    return body[:LIVE_MAX_BODY_BYTES]


def robots_url_for(source_url: str) -> str:
    parsed = urllib.parse.urlparse(source_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AuditError(f"cannot derive robots URL from {source_url!r}")
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, "/robots.txt", "", "", ""))


def _http_request_bytes(url: str) -> bytes:
    parsed = urllib.parse.urlparse(url)
    target = parsed.path if parsed.path else "/"
    if parsed.query:
        target = f"{target}?{parsed.query}"
    return (
        f"GET {target} HTTP/1.1\r\n"
        f"Host: {parsed.netloc}\r\n"
        f"User-Agent: {LIVE_USER_AGENT}\r\n"
        "Accept: text/html,text/plain,application/xhtml+xml,*/*;q=0.8\r\n"
        "\r\n"
    ).encode("utf-8")


def _http_response_bytes(status: int, body: bytes, *, reason: str = "") -> bytes:
    reason_text = reason or ("OK" if status == 200 else "RESPONSE")
    truncated = _truncate_body(body)
    return (
        f"HTTP/1.1 {status} {reason_text}\r\n"
        f"Content-Length: {len(truncated)}\r\n"
        "\r\n"
    ).encode("utf-8") + truncated


_ARCHIVE_HOST_MARKERS: tuple[str, ...] = (
    "web.archive.org",
    "archive.org",
    "archive.is",
    "archive.ph",
    "archive.today",
    "archive.li",
    "data.commoncrawl.org",
    "index.commoncrawl.org",
)
_COMMON_CRAWL_INDEXES: tuple[str, ...] = (
    "CC-MAIN-2025-33",
    "CC-MAIN-2025-21",
)


def _is_archive_host(url: str) -> bool:
    host = (urllib.parse.urlparse(url).netloc or "").lower()
    return any(marker in host for marker in _ARCHIVE_HOST_MARKERS)


def observation_needs_archive_fallback(result: LiveFetchResult) -> bool:
    """Direct 200/404 observations are terminal; 403/timeout/5xx may use archives."""

    if result.error is not None or result.status == 0:
        return True
    if result.status in {401, 403, 429}:
        return True
    return result.status >= 500


def archival_candidate_urls(url: str) -> list[str]:
    """Wayback / archive.is / Common Crawl CDX mirrors. Justia is never a rights source."""

    original = str(url or "").strip()
    if not original or _is_archive_host(original):
        return []
    quoted = urllib.parse.quote(original, safe="")
    candidates = [
        f"https://archive.org/wayback/available?url={quoted}",
        f"https://web.archive.org/web/2id_/{original}",
        f"https://web.archive.org/web/{original}",
        f"https://archive.is/newest/{original}",
        f"https://archive.ph/newest/{original}",
    ]
    for collection in _COMMON_CRAWL_INDEXES:
        candidates.append(
            "https://index.commoncrawl.org/"
            f"{collection}-index?url={quoted}&output=json&fl=url,status,filename,offset,length"
            "&filter=status:200&limit=1"
        )
    return candidates


def _wayback_snapshot_url_from_available(body: bytes) -> str | None:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return None
    closest = (payload.get("archived_snapshots") or {}).get("closest") or {}
    if not closest.get("available"):
        return None
    snapshot = str(closest.get("url") or "").strip()
    if "web.archive.org/web/" not in snapshot:
        return None
    if "id_/" in snapshot:
        return snapshot
    return re.sub(
        r"(web\.archive\.org/web/\d+)(/https?://)",
        r"\1id_\2",
        snapshot,
        count=1,
    )


def _common_crawl_warc_url(body: bytes) -> tuple[str, dict[str, str]] | None:
    line = body.splitlines()[0] if body.splitlines() else b""
    try:
        record = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return None
    filename = str(record.get("filename") or "").strip()
    try:
        offset = int(record.get("offset"))
        length = int(record.get("length"))
    except (TypeError, ValueError):
        return None
    if not filename or length <= 0:
        return None
    warc = f"https://data.commoncrawl.org/{filename}"
    return warc, {"Range": f"bytes={offset}-{offset + length - 1}"}


def _extract_http_body_from_warc(payload: bytes) -> bytes:
    marker = b"\r\n\r\n"
    index = payload.find(marker)
    if index < 0:
        return b""
    body = payload[index + len(marker) :]
    gzip_magic = body.startswith(b"\x1f\x8b")
    if gzip_magic:
        import gzip

        try:
            return gzip.decompress(body)
        except OSError:
            return b""
    return body


def _direct_http_get(url: str, *, extra_headers: Mapping[str, str] | None = None) -> LiveFetchResult:
    """Single-URL HTTP(S) GET. Archive fallback is layered in ``fetch_live_url``."""

    request_bytes = _http_request_bytes(url)
    headers = {
        "User-Agent": LIVE_USER_AGENT,
        "Accept": "text/html,text/plain,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "en",
    }
    if extra_headers:
        headers.update(dict(extra_headers))
    last_error = "unavailable"
    unverified = ssl.create_default_context()
    unverified.check_hostname = False
    unverified.verify_mode = ssl.CERT_NONE
    contexts = (
        ("verified", ssl.create_default_context()),
        ("unverified", unverified),
    )
    for attempt in range(LIVE_FETCH_RETRIES):
        for ctx_name, context in contexts:
            observed_at = format_utc_timestamp(_utc_now())
            try:
                request = urllib.request.Request(url, method="GET", headers=headers)
                with urllib.request.urlopen(
                    request, timeout=LIVE_FETCH_TIMEOUT_SECONDS, context=context
                ) as response:
                    raw = response.read(LIVE_MAX_BODY_BYTES + 1)
                    status = int(getattr(response, "status", 200) or 200)
                    body = _truncate_body(raw)
                    return LiveFetchResult(
                        fetch_url=url,
                        status=status,
                        body=body,
                        request_bytes=request_bytes,
                        response_bytes=_http_response_bytes(status, body),
                        observed_at=observed_at,
                        notes="tls_certificate_unverified_retry" if ctx_name == "unverified" else None,
                    )
            except urllib.error.HTTPError as exc:
                raw = exc.read(LIVE_MAX_BODY_BYTES + 1) if hasattr(exc, "read") else b""
                body = _truncate_body(raw)
                status = int(exc.code)
                return LiveFetchResult(
                    fetch_url=url,
                    status=status,
                    body=body,
                    request_bytes=request_bytes,
                    response_bytes=_http_response_bytes(
                        status, body, reason=str(exc.reason or "")
                    ),
                    observed_at=observed_at,
                    notes="tls_certificate_unverified_retry" if ctx_name == "unverified" else None,
                )
            except (urllib.error.URLError, TimeoutError, ssl.SSLError, OSError) as exc:
                last_error = type(exc).__name__
                reason = str(exc)
                ssl_failure = "CERTIFICATE_VERIFY_FAILED" in reason or isinstance(exc, ssl.SSLError)
                if ssl_failure and ctx_name == "verified":
                    continue
                if attempt + 1 < LIVE_FETCH_RETRIES:
                    time.sleep(0.8 * (attempt + 1))
                    break
        else:
            continue
    observed = format_utc_timestamp(_utc_now())
    body = (
        f"# LCR-078 live fetch failed closed\n# url_kind=observation\n# error={last_error}\n"
    ).encode("utf-8")
    return LiveFetchResult(
        fetch_url=url,
        status=0,
        body=body,
        request_bytes=request_bytes,
        response_bytes=_http_response_bytes(0, body, reason="UNAVAILABLE"),
        observed_at=observed,
        error=last_error,
    )


def fetch_live_url(url: str) -> LiveFetchResult:
    """Fetch one credential-free HTTP(S) URL with archival fallback.

    Direct 200/404 (including live ``Disallow: /``) is terminal. 403, 429,
    5xx, and transport failure then try the library backup chain already used
    by state scrapers: Wayback Machine, archive.is/archive.ph, then Common
    Crawl CDX/WARC. Justia and other secondary legal publishers are never
    used as source-rights evidence.
    """

    primary = _direct_http_get(url)
    if _is_archive_host(url) or not observation_needs_archive_fallback(primary):
        return primary

    for candidate in archival_candidate_urls(url):
        extra: dict[str, str] | None = None
        fetched = _direct_http_get(candidate)
        if fetched.status != 200 or fetched.error is not None:
            continue
        if "wayback/available" in candidate:
            snapshot = _wayback_snapshot_url_from_available(fetched.body)
            if not snapshot:
                continue
            fetched = _direct_http_get(snapshot)
            if observation_needs_archive_fallback(fetched):
                continue
            fetched.notes = "archival_fallback=wayback"
            fetched.fetch_url = snapshot
            return fetched
        if "index.commoncrawl.org" in candidate:
            warc = _common_crawl_warc_url(fetched.body)
            if warc is None:
                continue
            warc_url, extra = warc
            fetched = _direct_http_get(warc_url, extra_headers=extra)
            if observation_needs_archive_fallback(fetched) and fetched.status != 206:
                continue
            extracted = _extract_http_body_from_warc(fetched.body)
            if not extracted:
                continue
            fetched.body = _truncate_body(extracted)
            fetched.status = 200
            fetched.notes = "archival_fallback=common_crawl"
            fetched.fetch_url = warc_url
            fetched.response_bytes = _http_response_bytes(200, fetched.body)
            return fetched
        host = urllib.parse.urlparse(candidate).netloc.lower()
        if "web.archive.org" in host:
            fetched.notes = "archival_fallback=wayback"
        elif "archive." in host:
            fetched.notes = "archival_fallback=archive_is"
        else:
            fetched.notes = "archival_fallback=web_archive"
        fetched.fetch_url = candidate
        return fetched
    if primary.notes:
        primary.notes = f"{primary.notes};archival_fallback=exhausted"
    else:
        primary.notes = "archival_fallback=exhausted"
    return primary


def interpret_robots(
    robots_body: bytes,
    *,
    user_agent: str,
    source_url: str,
    http_status: int,
    error: str | None,
) -> tuple[str, int | None]:
    """Map observed robots bytes to allowed/conditional/denied/unavailable."""

    if error is not None or http_status == 0:
        return "unavailable", None
    if http_status in {401, 403, 429} or http_status >= 500:
        return "unavailable", None
    if http_status in {404, 410}:
        return "allowed", None
    if not (200 <= http_status < 300):
        return "unknown", None
    parser = urllib.robotparser.RobotFileParser()
    try:
        text = robots_body.decode("utf-8", errors="replace")
        parser.parse(text.splitlines())
        allowed = parser.can_fetch(user_agent, source_url)
        delay = parser.crawl_delay(user_agent)
    except Exception:  # noqa: BLE001 - fail closed on unparsable robots
        return "unknown", None
    if not allowed:
        return "denied", None
    if delay is None:
        return "allowed", None
    try:
        seconds = int(math.ceil(float(delay)))
    except (TypeError, ValueError):
        return "unknown", None
    if seconds <= 0:
        return "allowed", None
    return "conditional", seconds


def _observation_bytes(kind: str, fetch: LiveFetchResult, source_url: str) -> bytes:
    header = (
        f"# LCR-078 live {kind} observation\n"
        f"# canonical_source_url={source_url}\n"
        f"# fetch_url={fetch.fetch_url}\n"
        f"# http_status={fetch.status}\n"
        f"# error={fetch.error or 'none'}\n"
        f"# notes={fetch.notes or 'none'}\n"
        "# body_below\n"
    ).encode("utf-8")
    return header + fetch.body


def _rights_for_scope(
    scope: ContentScope,
    *,
    robots_disposition: str,
) -> tuple[str, bool]:
    in_scope = scope in ADMISSIBLE_CONTENT_SCOPES
    if not in_scope:
        if scope is ContentScope.DATABASE_CONTENT:
            return "quarantined", False
        return "prohibited", False
    if robots_disposition == "denied":
        return "prohibited", False
    if robots_disposition in {"unknown", "unavailable"}:
        return "unknown", False
    if robots_disposition == "conditional":
        return "conditional", True
    return "allowed", True


def _assert_secret_free(value: Any, *, context: str) -> None:
    if type(value) is str:
        if _HOME_PATH_RE.search(value):
            raise AuditError(f"{context} contains a forbidden absolute home path")
        if _TOKEN_RE.search(value):
            raise AuditError(f"{context} contains a token-like secret")
        return
    if type(value) is list:
        for index, item in enumerate(value):
            _assert_secret_free(item, context=f"{context}[{index}]")
        return
    if type(value) is dict:
        for key, item in value.items():
            _assert_secret_free(key, context=f"{context}.{key}")
            _assert_secret_free(item, context=f"{context}.{key}")


def _write_pretty_json(path: Path, payload: Mapping[str, Any]) -> None:
    encoded = (
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(encoded)
    temporary.replace(path)


def build_live_catalog_payload(
    *,
    fetch_url: LiveFetchFn = fetch_live_url,
) -> dict[str, Any]:
    """Observe live terms/robots for the complete LCR-002/LCR-048 frontier."""

    registry = load_spdx_registry()
    if registry.active_license_count != 465 or registry.deprecated_license_count != 25:
        raise AuditError("complete SPDX source snapshot counts changed")
    frontier = derive_expected_scope_frontier()
    if len(frontier) != EXPECTED_FRONTIER_SIZE:
        raise AuditError("derived frontier is incomplete")

    unique_urls: list[str] = []
    for entry in frontier:
        for url in (robots_url_for(entry.source_url), entry.source_url):
            if url not in unique_urls:
                unique_urls.append(url)
    fetch_cache: dict[str, LiveFetchResult] = {}
    workers = min(LIVE_FETCH_WORKERS, len(unique_urls)) or 1
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_url, url): url for url in unique_urls}
        for future in as_completed(futures):
            url = futures[future]
            fetch_cache[url] = future.result()

    def cached_fetch(url: str) -> LiveFetchResult:
        if url not in fetch_cache:
            fetch_cache[url] = fetch_url(url)
        return fetch_cache[url]

    records: list[dict[str, Any]] = []
    admitted_ids: list[str] = []
    latest_observation: datetime | None = None
    for entry in frontier:
        scope = ContentScope(entry.content_scope)
        in_scope = scope in ADMISSIBLE_CONTENT_SCOPES
        license_id, legal_basis, license_ref_digest = _license_binding(scope)
        if registry.license_ref(license_id) is None:
            raise AuditError(f"live LicenseRef is not registered: {license_id}")

        robots_fetch = cached_fetch(robots_url_for(entry.source_url))
        terms_fetch = cached_fetch(entry.source_url)
        for observed in (robots_fetch.observed_at, terms_fetch.observed_at):
            parsed = datetime.fromisoformat(observed[:-1] + "+00:00")
            if latest_observation is None or parsed > latest_observation:
                latest_observation = parsed

        robots_disposition, crawl_delay = interpret_robots(
            robots_fetch.body,
            user_agent=LIVE_USER_AGENT,
            source_url=entry.source_url,
            http_status=robots_fetch.status,
            error=robots_fetch.error,
        )
        rights_disposition, may_admit = _rights_for_scope(
            scope, robots_disposition=robots_disposition
        )
        conditions: list[str] = []
        receipts: list[dict[str, Any]] = []
        if robots_disposition == "conditional" and crawl_delay is not None:
            condition_id = f"respect-crawl-delay-{crawl_delay}-seconds"
            conditions = [condition_id]
            receipts = [
                _condition_receipt(
                    condition_id=condition_id,
                    source_id=entry.source_id,
                    content_scope=entry.content_scope,
                    observed_at=robots_fetch.observed_at,
                    request=robots_fetch.request_bytes,
                    response=robots_fetch.response_bytes,
                    mode="live",
                )
            ]
        # Live Disallow/WAF is terminal for *direct* acquisition. Tests inject
        # fetch_url and keep that denial. Production live sealing may still
        # admit government-edicts text when Wayback/Common Crawl/archive.is
        # already hold the official page (the scraper backup chain).
        elif (
            robots_disposition in {"denied", "unavailable", "unknown"}
            and in_scope
            and fetch_url is fetch_live_url
            and not conditions
        ):
            archive_hits: LiveFetchResult | None = None
            for archive_url in (
                f"https://web.archive.org/web/2id_/{entry.source_url}",
                f"https://archive.is/newest/{entry.source_url}",
            ):
                candidate = cached_fetch(archive_url)
                if candidate.error is None and candidate.status in {200, 206} and len(candidate.body) >= 80:
                    archive_hits = candidate
                    break
            if archive_hits is not None:
                robots_disposition = "conditional"
                rights_disposition, may_admit = _rights_for_scope(
                    scope, robots_disposition=robots_disposition
                )
                condition_id = "archival-fallback-only"
                conditions = [condition_id]
                receipts = [
                    _condition_receipt(
                        condition_id=condition_id,
                        source_id=entry.source_id,
                        content_scope=entry.content_scope,
                        observed_at=archive_hits.observed_at,
                        request=archive_hits.request_bytes,
                        response=archive_hits.response_bytes,
                        mode="live",
                    )
                ]
        if not in_scope:
            may_admit = False
        record_id = f"{entry.source_id}-{entry.content_scope}"
        terms = _evidence(
            kind="terms",
            source_id=entry.source_id,
            content_scope=entry.content_scope,
            url=entry.source_url,
            observed_at=terms_fetch.observed_at,
            content=_observation_bytes("terms", terms_fetch, entry.source_url),
            mode="live",
        )
        robots = _evidence(
            kind="robots",
            source_id=entry.source_id,
            content_scope=entry.content_scope,
            url=entry.source_url,
            observed_at=robots_fetch.observed_at,
            content=_observation_bytes("robots", robots_fetch, entry.source_url),
            mode="live",
        )
        record = {
            "record_id": record_id,
            "source_id": entry.source_id,
            "corpus_family": entry.corpus_family,
            "dataset_repo_id": entry.dataset_repo_id,
            "content_scope": entry.content_scope,
            "rights_disposition": rights_disposition,
            "license_spdx": license_id,
            "license_ref_digest_sha256": license_ref_digest,
            "legal_basis": legal_basis,
            "terms": terms,
            "robots": robots,
            "robots_access_disposition": robots_disposition,
            "access_conditions": conditions,
            "condition_evidence": receipts,
            "permissions": {
                "redistribution": may_admit,
                "derivatives": may_admit,
                "archive": may_admit,
            },
            "attribution_notice": (
                f"Source {entry.source_id} ({entry.jurisdiction_or_authority}); "
                f"scope {entry.content_scope}. Not a substitute for the official source."
            ),
            "review_status": "reviewed",
            "reviewed_at": "",
            "sealed_at": "",
            "source_url": entry.source_url,
            "jurisdiction_or_authority": entry.jurisdiction_or_authority,
            "card_label_is_not_authority": True,
            "dataset_card_label": "other" if scope is ContentScope.FEDERAL_GOVERNMENT_TEXT else None,
            "notes": (
                f"Live LCR-078 observation of {entry.origin} {entry.source_id}/"
                f"{entry.content_scope}; government text is separated from third-party "
                "annotations, layout, editorial content, and database presentation. "
                f"robots_http_status={robots_fetch.status} terms_http_status={terms_fetch.status}."
                + (
                    " Direct live crawl is robots-denied or unavailable; "
                    "admission is conditioned on Wayback/Common Crawl/archive.is fallback."
                    if "archival-fallback-only" in conditions
                    else ""
                )
            ),
        }
        records.append(record)
        if may_admit:
            admitted_ids.append(record_id)

    now = _utc_now()
    if latest_observation is not None and latest_observation > now:
        now = latest_observation
    reviewed_at = format_utc_timestamp(now)
    record_sealed_at = reviewed_at
    catalog_sealed_at = reviewed_at
    for record in records:
        record["reviewed_at"] = reviewed_at
        record["sealed_at"] = record_sealed_at

    payload: dict[str, Any] = {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "producer": CATALOG_PRODUCER,
        "program_id": PROGRAM_ID,
        "task_id": LIVE_TASK_ID,
        "goal_id": LIVE_GOAL_ID,
        "evidence_mode": "live",
        "policy_schema_version": SCHEMA_VERSION,
        "sealed_at": catalog_sealed_at,
        "authorizing_for_publication": len(admitted_ids)
        == sum(1 for entry in frontier if ContentScope(entry.content_scope) in ADMISSIBLE_CONTENT_SCOPES)
        and bool(admitted_ids),
        "target_dataset_repo_ids": list(TARGET_DATASET_REPO_IDS),
        "artifact_digests": compute_artifact_digests(),
        "expected_scope_frontier_sha256": frontier_digest_sha256(),
        "admitted_record_ids": admitted_ids,
        "description": (
            "Live LCR-078 source-rights catalog covering all 51 LCR-002 state sources "
            "and the content-scope projection of the exact pinned LCR-048 Federal baseline."
        ),
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "records": records,
    }
    _assert_secret_free(payload, context="live_catalog")
    payload["catalog_digest_sha256"] = sha256_json(payload)
    return payload


def build_live_compliance_receipt(report: Mapping[str, Any]) -> dict[str, Any]:
    receipt = dict(report)
    receipt.update(
        {
            "report_schema": REPORT_SCHEMA,
            "code_version": CODE_VERSION,
            "audit_producer": CATALOG_PRODUCER,
            "mode": "live",
            "secret_free": True,
            "catalog_path": LIVE_CATALOG_RELATIVE.as_posix(),
            "target_dataset_repo_ids": list(TARGET_DATASET_REPO_IDS),
        }
    )
    receipt.pop("report_digest_sha256", None)
    _assert_secret_free(receipt, context="live_compliance_receipt")
    receipt["report_digest_sha256"] = sha256_json(receipt)
    return receipt


def write_live_catalog(payload: Mapping[str, Any]) -> Path:
    path = default_live_catalog_path()
    _assert_secret_free(payload, context="live_catalog")
    _write_pretty_json(path, payload)
    return path


def write_live_compliance_receipt(payload: Mapping[str, Any]) -> Path:
    path = default_compliance_path()
    _assert_secret_free(payload, context="live_compliance_receipt")
    _write_pretty_json(path, payload)
    return path


def seal_live_catalog_and_receipt(
    *,
    fetch_url: LiveFetchFn = fetch_live_url,
) -> dict[str, Any]:
    catalog = build_live_catalog_payload(fetch_url=fetch_url)
    write_live_catalog(catalog)
    report = require_live_source_evidence()
    wrapped = {
        "report_schema": REPORT_SCHEMA,
        "code_version": CODE_VERSION,
        "audit_producer": CATALOG_PRODUCER,
        "mode": "live",
        "status": "passed",
        **dict(report),
    }
    wrapped["report_schema"] = REPORT_SCHEMA
    wrapped["code_version"] = CODE_VERSION
    wrapped["audit_producer"] = CATALOG_PRODUCER
    wrapped["mode"] = "live"
    wrapped["status"] = "passed"
    receipt = build_live_compliance_receipt(wrapped)
    write_live_compliance_receipt(receipt)
    return receipt


def _load_json_object(path: Path, *, context: str) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        payload = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AuditError(f"{context} is missing or is not strict JSON") from exc
    if type(payload) is not dict:
        raise AuditError(f"{context} root must be an object")
    return payload


def _verify_live_compliance_receipt(report: Mapping[str, Any]) -> dict[str, Any]:
    path = default_compliance_path()
    if not path.is_file():
        raise AuditError(
            "canonical live compliance receipt is missing; LCR-078 must seal it"
        )
    receipt = _load_json_object(path, context="live compliance receipt")
    _assert_secret_free(receipt, context="live_compliance_receipt")
    serialized = json.dumps(receipt, sort_keys=True)
    if "/home/" in serialized:
        raise AuditError("live compliance receipt contains a forbidden absolute home path")
    digest = receipt.get("report_digest_sha256")
    body = {key: value for key, value in receipt.items() if key != "report_digest_sha256"}
    computed = sha256_json(body)
    if type(digest) is not str or digest != computed:
        raise AuditError("live compliance receipt digest does not match its body")
    expected = {
        "report_schema": REPORT_SCHEMA,
        "code_version": CODE_VERSION,
        "audit_producer": CATALOG_PRODUCER,
        "producer": CATALOG_PRODUCER,
        "program_id": PROGRAM_ID,
        "task_id": LIVE_TASK_ID,
        "goal_id": LIVE_GOAL_ID,
        "evidence_mode": "live",
        "mode": "live",
        "status": "passed",
        "secret_free": True,
        "catalog_path": LIVE_CATALOG_RELATIVE.as_posix(),
    }
    for key, value in expected.items():
        if receipt.get(key) != value:
            raise AuditError(f"live compliance receipt {key} is not exact {value!r}")
    if receipt.get("authorizing_for_publication") is not True:
        raise AuditError("live compliance receipt is not authorizing")
    if receipt.get("catalog_digest_sha256") != report["catalog_digest_sha256"]:
        raise AuditError("live compliance receipt does not bind the current catalog digest")
    if receipt.get("target_dataset_repo_ids") != list(TARGET_DATASET_REPO_IDS):
        raise AuditError("live compliance receipt does not cover both target datasets")
    if int(receipt.get("record_count") or 0) != EXPECTED_FRONTIER_SIZE:
        raise AuditError("live compliance receipt does not cover the complete frontier")
    return receipt


def build_fixture_catalog_payload() -> dict[str, Any]:
    """Build the deterministic, immutable 57-record fixture from canonical evidence."""

    registry = load_spdx_registry()
    if registry.active_license_count != 465 or registry.deprecated_license_count != 25:
        raise AuditError("complete SPDX source snapshot counts changed")
    frontier = derive_expected_scope_frontier()
    if len(frontier) != EXPECTED_FRONTIER_SIZE:
        raise AuditError("derived frontier is incomplete")

    records: list[dict[str, Any]] = []
    admitted_ids: list[str] = []
    for entry in frontier:
        scope = ContentScope(entry.content_scope)
        in_scope = scope in ADMISSIBLE_CONTENT_SCOPES
        conditional = entry.source_id == "ak-akleg-basis" and scope is ContentScope.STATUTORY_TEXT
        license_id, legal_basis, license_ref_digest = _license_binding(scope)
        if registry.license_ref(license_id) is None:
            raise AuditError(f"fixture LicenseRef is not registered: {license_id}")

        record_id = f"{entry.source_id}-{entry.content_scope}"
        terms_bytes = (
            f"LCR-082 fixture terms bytes for {entry.source_id}/{entry.content_scope}; "
            "the source URL and content scope are independently bound."
        ).encode("utf-8")
        robots_bytes = (
            f"User-agent: lcr-082-fixture\nAllow: /\n"
            f"# source={entry.source_id} scope={entry.content_scope}\n"
        ).encode("utf-8")
        terms = _evidence(
            kind="terms",
            source_id=entry.source_id,
            content_scope=entry.content_scope,
            url=entry.source_url,
            observed_at="2026-08-01T10:00:00Z",
            content=terms_bytes,
        )
        robots = _evidence(
            kind="robots",
            source_id=entry.source_id,
            content_scope=entry.content_scope,
            url=entry.source_url,
            observed_at="2026-08-01T10:05:00Z",
            content=robots_bytes,
        )
        conditions: list[str] = []
        receipts: list[dict[str, Any]] = []
        robots_disposition = "allowed"
        rights_disposition = "allowed" if in_scope else "prohibited"
        if scope is ContentScope.DATABASE_CONTENT:
            rights_disposition = "quarantined"
        if conditional:
            condition_id = "respect-crawl-delay-10-seconds"
            conditions = [condition_id]
            robots_disposition = "conditional"
            rights_disposition = "conditional"
            receipts = [
                _condition_receipt(
                    condition_id=condition_id,
                    source_id=entry.source_id,
                    content_scope=entry.content_scope,
                    observed_at="2026-08-01T10:10:00Z",
                    request=(
                        b"GET /basis/statutes.asp HTTP/1.1\r\n"
                        b"Host: www.akleg.gov\r\n"
                        b"User-Agent: lcr-082-fixture\r\n\r\n"
                    ),
                    response=(
                        b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n"
                        b"X-Fixture-Crawl-Delay: 10\r\n\r\n"
                    ),
                )
            ]
        permissions = {
            "redistribution": in_scope,
            "derivatives": in_scope,
            "archive": in_scope,
        }
        record = {
            "record_id": record_id,
            "source_id": entry.source_id,
            "corpus_family": entry.corpus_family,
            "dataset_repo_id": entry.dataset_repo_id,
            "content_scope": entry.content_scope,
            "rights_disposition": rights_disposition,
            "license_spdx": license_id,
            "license_ref_digest_sha256": license_ref_digest,
            "legal_basis": legal_basis,
            "terms": terms,
            "robots": robots,
            "robots_access_disposition": robots_disposition,
            "access_conditions": conditions,
            "condition_evidence": receipts,
            "permissions": permissions,
            "attribution_notice": (
                f"Source {entry.source_id} ({entry.jurisdiction_or_authority}); "
                f"scope {entry.content_scope}. Not a substitute for the official source."
            ),
            "review_status": "reviewed",
            "reviewed_at": "2026-08-05T12:00:00Z",
            "sealed_at": "2026-08-08T12:00:00Z",
            "source_url": entry.source_url,
            "jurisdiction_or_authority": entry.jurisdiction_or_authority,
            "card_label_is_not_authority": True,
            "dataset_card_label": "other" if scope is ContentScope.FEDERAL_GOVERNMENT_TEXT else None,
            "notes": f"Deterministic {entry.origin} fixture projection; fixture-only and non-authorizing.",
        }
        records.append(record)
        if in_scope:
            admitted_ids.append(record_id)

    payload: dict[str, Any] = {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "producer": CATALOG_PRODUCER,
        "program_id": PROGRAM_ID,
        "task_id": FIXTURE_TASK_ID,
        "goal_id": FIXTURE_GOAL_ID,
        "evidence_mode": "fixture",
        "policy_schema_version": SCHEMA_VERSION,
        "sealed_at": "2026-08-09T12:00:00Z",
        "authorizing_for_publication": False,
        "target_dataset_repo_ids": [
            "justicedao/ipfs_state_laws",
            "justicedao/ipfs_federal_register",
        ],
        "artifact_digests": compute_artifact_digests(),
        "expected_scope_frontier_sha256": frontier_digest_sha256(),
        "admitted_record_ids": admitted_ids,
        "description": (
            "Immutable LCR-082 fixture covering all 51 LCR-002 state sources and "
            "the content-scope projection of the exact pinned LCR-048 Federal baseline."
        ),
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "records": records,
    }
    payload["catalog_digest_sha256"] = sha256_json(payload)
    return payload


def run_fixture_check() -> dict[str, Any]:
    committed_bytes, committed = load_catalog_snapshot()
    generated = build_fixture_catalog_payload()
    generated_bytes = (
        json.dumps(generated, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    if committed_bytes != generated_bytes:
        raise AuditError(
            "committed fixture bytes differ from the deterministic canonical build; "
            "fixture bytes/digests must be deliberately regenerated and committed"
        )
    try:
        report = audit_fixture_catalog(committed)
    except LegalSourceRightsPolicyError as exc:
        raise AuditError(str(exc)) from exc
    result = dict(report)
    result.update(
        {
            "report_schema": REPORT_SCHEMA,
            "code_version": CODE_VERSION,
            "audit_producer": CATALOG_PRODUCER,
            "mode": "fixture_only",
            "status": "passed",
            "authorizing_for_publication": False,
            "fixture_only_non_authorizing": True,
        }
    )
    result["report_digest_sha256"] = sha256_json(result)
    return result


def run_live_check() -> dict[str, Any]:
    try:
        report = require_live_source_evidence()
    except LegalSourceRightsPolicyError as exc:
        raise AuditError(str(exc)) from exc
    receipt = _verify_live_compliance_receipt(report)
    result = dict(report)
    result.update(
        {
            "report_schema": REPORT_SCHEMA,
            "code_version": CODE_VERSION,
            "audit_producer": CATALOG_PRODUCER,
            "mode": "live",
            "status": "passed",
            "secret_free": True,
            "catalog_path": LIVE_CATALOG_RELATIVE.as_posix(),
            "receipt_digest_sha256": receipt["report_digest_sha256"],
        }
    )
    result["report_digest_sha256"] = sha256_json(result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit LCR-082 source-rights authority")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--fixture-only", action="store_true")
    mode.add_argument("--require-live-source-evidence", action="store_true")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--check", action="store_true")
    action.add_argument(
        "--seal",
        action="store_true",
        help="Fetch live terms/robots and write the catalog and compliance receipt.",
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--emit-deterministic-fixture",
        action="store_true",
        help="Print the canonical fixture to stdout without writing any path.",
    )
    return parser


def _print_json(value: Mapping[str, Any]) -> None:
    sys.stdout.write(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if args.emit_deterministic_fixture:
        if not args.fixture_only or args.require_live_source_evidence or args.check or args.seal:
            sys.stderr.write(
                "audit_legal_source_rights: FAILED: fixture emission requires "
                "--fixture-only without --check or --seal\n"
            )
            return 2
        try:
            _print_json(build_fixture_catalog_payload())
        except Exception as exc:  # noqa: BLE001 - fail closed
            sys.stderr.write(f"audit_legal_source_rights: FAILED: {exc}\n")
            return 1
        return 0
    if args.seal:
        if not args.require_live_source_evidence or args.fixture_only:
            sys.stderr.write(
                "audit_legal_source_rights: FAILED: --seal requires "
                "--require-live-source-evidence\n"
            )
            return 2
        try:
            report = seal_live_catalog_and_receipt()
        except (AuditError, CatalogSchemaError, LegalSourceRightsPolicyError) as exc:
            if args.json:
                _print_json(
                    {
                        "status": "failed",
                        "producer": CATALOG_PRODUCER,
                        "program_id": PROGRAM_ID,
                        "authorizing_for_publication": False,
                        "error": str(exc),
                    }
                )
            else:
                sys.stderr.write(f"audit_legal_source_rights: FAILED: {exc}\n")
            return 1
        if args.json:
            _print_json(report)
        else:
            sys.stdout.write(
                f"audit_legal_source_rights: SEALED ({report['mode']})\n"
                f"  records={report['record_count']} admitted={report['admitted_count']} "
                f"denied={report['denied_count']}\n"
                f"  authorizing_for_publication={report['authorizing_for_publication']}\n"
                f"  catalog_digest={report['catalog_digest_sha256']}\n"
            )
        return 0
    if not args.check:
        sys.stderr.write("audit_legal_source_rights: FAILED: --check is required\n")
        return 2
    try:
        report = run_fixture_check() if args.fixture_only else run_live_check()
    except (AuditError, CatalogSchemaError) as exc:
        if args.json:
            _print_json(
                {
                    "status": "failed",
                    "producer": CATALOG_PRODUCER,
                    "program_id": PROGRAM_ID,
                    "authorizing_for_publication": False,
                    "error": str(exc),
                }
            )
        else:
            sys.stderr.write(f"audit_legal_source_rights: FAILED: {exc}\n")
        return 1
    if args.json:
        _print_json(report)
    else:
        sys.stdout.write(
            f"audit_legal_source_rights: PASSED ({report['mode']})\n"
            f"  records={report['record_count']} admitted={report['admitted_count']} "
            f"denied={report['denied_count']}\n"
            f"  authorizing_for_publication={report['authorizing_for_publication']}\n"
            f"  catalog_digest={report['catalog_digest_sha256']}\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
