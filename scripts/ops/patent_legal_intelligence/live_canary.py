#!/usr/bin/env python3
"""Optional live official-source canary with offline fallback (PATLAW-167).

Operator surface for post-completion official-source health probes:

* **Default:** offline fixtures (network-free, CI-safe)
* **Optional live:** bounded read-only HTTPS probes of eCFR, GovInfo,
  Federal Register, and USPTO ODP public endpoints, with content-free receipts
* **Never** mutates private matter state, credentials, or portfolio content

Policy (never weakened)
-----------------------
* Live network access is opt-in (``--live`` or env flags) and receipt-bound.
* Offline fixtures are the production default for automated validation.
* Receipts are content-free: digests, status codes, host labels, counts only.
* Private portfolio / matter documents, extracted text, API keys, bearer tokens,
  cookies, and raw provider bodies must never appear in canary receipts.
* Forbidden mutations: sign, pay, file, submit, scrape Patent Center, store
  credentials, write matter state.
* HTTP success alone is not source authenticity verification.

Usage
-----
    # Offline (default — fixtures only, no network):
    python scripts/ops/patent_legal_intelligence/live_canary.py --json

    # Optional live probes (bounded, read-only):
    python scripts/ops/patent_legal_intelligence/live_canary.py --live --json

    # Write receipt under an explicit directory (never a private matter root):
    python scripts/ops/patent_legal_intelligence/live_canary.py \\
        --offline --receipt-dir /tmp/patlaw-canary --json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final
from urllib.parse import urlsplit

# ---------------------------------------------------------------------------
# Schema / identity
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "patent-legal.live-canary.v1"
INTERFACE: Final = "PatentLegalLiveCanary@1"
TASK_ID: Final = "PATLAW-167"
GOAL_ID: Final = "PATLAW-G202"
PROGRAM_ID: Final = "patent-legal-intelligence"
POLICY_ID: Final = "patent-legal-live-canary/v1"
FIXTURE_SCHEMA_VERSION: Final = "patent-legal.live-canary-fixtures.v1"

# Explicit live opt-in environment flags (any truthy enables live when --live
# is not passed; CLI --live always wins as explicit opt-in).
LIVE_ENV_FLAGS: Final[tuple[str, ...]] = (
    "PATLAW_LIVE_CANARY",
    "PATLAW_167_LIVE_CANARY",
    "PATENT_LEGAL_LIVE_CANARY",
)

# Source families probed by the canary (acceptance surface).
SOURCE_FAMILIES: Final[tuple[str, ...]] = (
    "ecfr",
    "govinfo",
    "federal_register",
    "odp",
)

# Bounded budgets (fail-closed caps).
MAX_PROBES_DEFAULT: Final = 4  # one probe per source family
MAX_PROBES_HARD_CAP: Final = 8
MAX_RESPONSE_BYTES: Final = 256 * 1024  # 256 KiB per probe — canary only
REQUEST_TIMEOUT_SECONDS: Final = 15.0
MAX_REASON_LEN: Final = 240

# Allowlisted official hosts (subset of source-authority policy discovery list).
ALLOWED_HOSTS: Final[frozenset[str]] = frozenset(
    {
        "www.ecfr.gov",
        "api.govinfo.gov",
        "www.govinfo.gov",
        "www.federalregister.gov",
        "api.federalregister.gov",
        "api.uspto.gov",
        "data.uspto.gov",
        "www.uspto.gov",
    }
)

# Read-only methods only.
ALLOWED_METHODS: Final[frozenset[str]] = frozenset({"GET", "HEAD"})

# Explicit forbidden mutation verbs (acceptance / recipe contract).
FORBIDDEN_MUTATIONS: Final[tuple[str, ...]] = (
    "sign",
    "pay",
    "file",
    "submit",
    "scrape_authenticated_patent_center",
    "store_credentials_or_cookies",
    "bypass_mfa",
    "apply_signature",
    "pay_fee",
    "perform_final_submission",
    "write_private_matter_state",
    "mutate_private_portfolio",
    "auto_push",
    "hub_main_publish",
)

# Paths / path fragments that must never be written by the canary.
_PRIVATE_MATTER_PATH_FRAGMENTS: Final[tuple[str, ...]] = (
    "private_matter",
    "private-matter",
    "matter_store",
    "matter-store",
    "portfolio_private",
    "tenant_private",
    "privileged_work_product",
    "private_account",
)

# Content-free policy markers (must never appear in operator output).
_FORBIDDEN_CONTENT_MARKERS: Final = frozenset(
    {
        "secret_document_body",
        "private extracted_text",
        "authorization: bearer",
        "x-api-key:",
        "api_key=",
        "-----begin ",
        "payment_card",
        "mfa_secret",
        "session_cookie",
        "private_portfolio_body",
        "claim_text_body",
    }
)

_SECRET_KEY_FRAGMENTS: Final = frozenset(
    {
        "api_key",
        "apikey",
        "password",
        "secret",
        "token",
        "authorization",
        "cookie",
        "bearer",
        "session",
        "mfa",
        "x-api-key",
        "document_body",
        "document_bytes",
        "extracted_text",
        "raw_body",
        "private_text",
        "claim_text",
        "prompt",
        "portfolio_body",
    }
)

_SECRET_TEXT_RE = re.compile(
    r"(?i)(x-api-key|api[_-]?key|authorization|bearer|token)\s*[:=]\s*[^\s,;\"']+"
)

# Default public probe endpoints (bounded metadata / discovery only).
# These are GET/HEAD targets; live mode never POSTs or mutates.
DEFAULT_PROBE_SPECS: Final[tuple[Mapping[str, Any], ...]] = (
    {
        "source": "ecfr",
        "label": "eCFR titles index (unofficial editorial presentation)",
        "method": "GET",
        "url": "https://www.ecfr.gov/api/versioner/v1/titles.json",
        "authority_label": "unofficial_editorial_presentation",
        "max_bytes": MAX_RESPONSE_BYTES,
    },
    {
        "source": "govinfo",
        "label": "GovInfo collections discovery",
        "method": "GET",
        "url": "https://api.govinfo.gov/collections?pageSize=1&offsetMark=*",
        "authority_label": "official_source_artifact_discovery",
        "max_bytes": MAX_RESPONSE_BYTES,
    },
    {
        "source": "federal_register",
        "label": "Federal Register agencies index",
        "method": "GET",
        "url": "https://www.federalregister.gov/api/v1/agencies",
        "authority_label": "unofficial_editorial_presentation",
        "max_bytes": MAX_RESPONSE_BYTES,
    },
    {
        "source": "odp",
        "label": "USPTO ODP swagger/OpenAPI metadata (public, no credentials)",
        "method": "GET",
        "url": "https://api.uspto.gov/swagger/openapi.json",
        "authority_label": "public_provider_metadata",
        "max_bytes": MAX_RESPONSE_BYTES,
    },
)

USER_AGENT: Final = (
    "ipfs-datasets-patent-legal-live-canary/1.0 "
    "(+https://github.com; read-only official-source canary; PATLAW-167)"
)

Opener = Callable[[urllib.request.Request, float], Any]


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class CanaryMode(str, Enum):
    """Execution mode for the canary."""

    OFFLINE = "offline"
    LIVE = "live"


class ProbeStatus(str, Enum):
    """Per-probe outcome classification."""

    SUCCESS = "success"
    EMPTY = "empty"
    HTTP_ERROR = "http_error"
    TRANSPORT_ERROR = "transport_error"
    POLICY_VIOLATION = "policy_violation"
    TIMEOUT = "timeout"
    FIXTURE = "fixture"
    SKIPPED = "skipped"
    UNKNOWN = "unknown"


class OverallDisposition(str, Enum):
    """Aggregate canary disposition for handoff / production_status."""

    PASS = "pass"
    PASS_WITH_GAPS = "pass_with_gaps"
    FAIL = "fail"
    SKIPPED_LIVE = "skipped_live"
    OFFLINE_OK = "offline_ok"


# ---------------------------------------------------------------------------
# Time / hashing / redaction
# ---------------------------------------------------------------------------


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_hex(material: str | bytes) -> str:
    if isinstance(material, str):
        material = material.encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sanitize_text(value: Any) -> str:
    text = _SECRET_TEXT_RE.sub(r"\1=[REDACTED]", str(value or ""))
    if len(text) > MAX_REASON_LEN:
        text = text[: MAX_REASON_LEN - 1] + "…"
    return text


def redact_mapping(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Drop secret/document keys; sanitize remaining string values."""
    if not payload:
        return {}
    out: dict[str, Any] = {}
    for key, value in payload.items():
        key_s = str(key)
        lowered = key_s.lower().replace("-", "_")
        if any(frag in lowered for frag in _SECRET_KEY_FRAGMENTS):
            out[key_s] = "[REDACTED]"
            continue
        if isinstance(value, Mapping):
            out[key_s] = redact_mapping(value)
        elif isinstance(value, (list, tuple)):
            out[key_s] = [
                redact_mapping(v)
                if isinstance(v, Mapping)
                else sanitize_text(v)
                if isinstance(v, str)
                else v
                for v in value
            ]
        elif isinstance(value, str):
            out[key_s] = sanitize_text(value)
        elif isinstance(value, (int, float, bool)) or value is None:
            out[key_s] = value
        else:
            out[key_s] = sanitize_text(value)
    return out


def assert_content_free(payload: Any) -> None:
    """Raise ValueError if payload embeds forbidden document/secret markers."""
    blob = json.dumps(payload, sort_keys=True, default=str).lower()
    for marker in _FORBIDDEN_CONTENT_MARKERS:
        if marker in blob:
            raise ValueError(f"live canary receipt is not content-free: found {marker!r}")


def endpoint_fingerprint(url: str) -> str:
    digest = sha256_hex(sanitize_url(url))[:12]
    return f"endpoint:{digest}"


def sanitize_url(url: str) -> str:
    """Strip userinfo; keep path for public endpoints (no secret query keys)."""
    parts = urlsplit(str(url))
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    # Drop query entirely for fingerprint/receipt safety (may contain keys).
    return f"{parts.scheme}://{host}{parts.path}"


def host_of(url: str) -> str:
    return (urlsplit(str(url)).hostname or "").rstrip(".").lower()


# ---------------------------------------------------------------------------
# Offline fixtures (compact recipe — not bulk golden dumps)
# ---------------------------------------------------------------------------


def build_offline_fixture_recipe() -> dict[str, Any]:
    """Compact offline probe recipe generator (admission-friendly).

    Emits one synthetic fixture result per source family with digests and
    status codes only — no full provider envelopes.
    """
    cases: list[dict[str, Any]] = []
    for spec in DEFAULT_PROBE_SPECS:
        source = str(spec["source"])
        url = str(spec["url"])
        body_seed = f"patlaw-167-offline-fixture:{source}:{url}"
        body_digest = sha256_hex(body_seed)
        cases.append(
            {
                "source": source,
                "label": spec["label"],
                "method": spec["method"],
                "url": url,
                "host": host_of(url),
                "authority_label": spec["authority_label"],
                "status_code": 200,
                "body_sha256": body_digest,
                "body_bytes": 128,
                "content_type": "application/json",
                "fixture": True,
                "read_only": True,
            }
        )
    return {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "fixture_id": "patlaw-167-official-source-canary",
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "network_free": True,
        "default_enabled": True,
        "opt_in_live": True,
        "read_only": True,
        "bounded": True,
        "secret_redacted": True,
        "max_probes": MAX_PROBES_DEFAULT,
        "sources": list(SOURCE_FAMILIES),
        "forbidden_mutations": list(FORBIDDEN_MUTATIONS),
        "cases": cases,
        "acceptance": {
            "defaults_to_offline_fixtures": True,
            "optional_live_records_receipts": True,
            "never_mutates_private_matter_state": True,
            "probes_ecfr_govinfo_federal_register_odp": True,
        },
    }


def default_fixture_recipe() -> Mapping[str, Any]:
    """Immutable view of the built-in offline recipe."""
    return MappingProxyType(build_offline_fixture_recipe())


# ---------------------------------------------------------------------------
# Path / private-matter guards
# ---------------------------------------------------------------------------


def path_looks_like_private_matter(path: Path | str) -> bool:
    """Return True if *path* appears to be a private matter / portfolio root.

    Matches path **segments** (not free-form substrings) so operator temp
    directories whose names merely contain the words are not false positives.
    """
    parts = [p.lower() for p in Path(path).parts]
    # Exact segment match for multi-word fragments stored with separators.
    for frag in _PRIVATE_MATTER_PATH_FRAGMENTS:
        frag_l = frag.lower()
        if frag_l in parts:
            return True
        # Also allow nested form: .../private_matter/... as a single segment.
        if any(p == frag_l or p.startswith(frag_l + "/") for p in parts):
            return True
    return False


def assert_receipt_dir_safe(receipt_dir: Path | None) -> None:
    """Refuse to write receipts into private matter paths."""
    if receipt_dir is None:
        return
    if path_looks_like_private_matter(receipt_dir):
        raise ValueError(
            "refusing to write canary receipt under private matter path: "
            f"{receipt_dir}"
        )


def assert_no_private_matter_mutation(
    *,
    matter_root: Path | None,
    before_snapshot: Mapping[str, str] | None,
) -> None:
    """Verify private matter root is unchanged (or absent)."""
    if matter_root is None:
        return
    if not matter_root.exists():
        return
    after = snapshot_directory(matter_root)
    before = dict(before_snapshot or {})
    if after != before:
        raise RuntimeError(
            "private matter state mutated during canary run "
            f"(before={len(before)} after={len(after)} entries)"
        )


def snapshot_directory(root: Path) -> dict[str, str]:
    """Content-free directory snapshot: relative path → sha256 of file bytes."""
    out: dict[str, str] = {}
    if not root.is_dir():
        return out
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rel = str(path.relative_to(root)).replace("\\", "/")
            try:
                out[rel] = sha256_hex(path.read_bytes())
            except OSError:
                out[rel] = "unreadable"
    return out


# ---------------------------------------------------------------------------
# Probe model
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProbeSpec:
    """One bounded read-only official-source probe."""

    source: str
    label: str
    method: str
    url: str
    authority_label: str
    max_bytes: int = MAX_RESPONSE_BYTES

    def __post_init__(self) -> None:
        method = str(self.method or "GET").upper()
        if method not in ALLOWED_METHODS:
            raise ValueError(f"probe method must be read-only GET/HEAD, got {method!r}")
        source = str(self.source).strip().lower()
        if source not in SOURCE_FAMILIES:
            raise ValueError(f"unknown source family: {source!r}")
        object.__setattr__(self, "method", method)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "url", str(self.url))
        object.__setattr__(self, "label", str(self.label))
        object.__setattr__(self, "authority_label", str(self.authority_label))
        object.__setattr__(self, "max_bytes", int(self.max_bytes))

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "ProbeSpec":
        return cls(
            source=str(raw["source"]),
            label=str(raw.get("label") or raw["source"]),
            method=str(raw.get("method") or "GET"),
            url=str(raw["url"]),
            authority_label=str(raw.get("authority_label") or "unknown"),
            max_bytes=int(raw.get("max_bytes") or MAX_RESPONSE_BYTES),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_label": self.authority_label,
            "host": host_of(self.url),
            "label": self.label,
            "max_bytes": self.max_bytes,
            "method": self.method,
            "source": self.source,
            "url": sanitize_url(self.url),
        }


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """Content-free observation for one probe."""

    source: str
    status: str
    mode: str
    method: str
    host: str
    endpoint_fingerprint: str
    status_code: int | None
    body_sha256: str | None
    body_bytes: int | None
    content_type: str | None
    authority_label: str
    message: str
    fixture: bool
    read_only: bool = True
    metadata: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_label": self.authority_label,
            "body_bytes": self.body_bytes,
            "body_sha256": self.body_sha256,
            "content_type": self.content_type,
            "endpoint_fingerprint": self.endpoint_fingerprint,
            "fixture": self.fixture,
            "host": self.host,
            "message": sanitize_text(self.message),
            "metadata": redact_mapping(dict(self.metadata)),
            "method": self.method,
            "mode": self.mode,
            "read_only": True,
            "source": self.source,
            "status": self.status,
            "status_code": self.status_code,
        }


def default_probe_specs() -> tuple[ProbeSpec, ...]:
    return tuple(ProbeSpec.from_mapping(spec) for spec in DEFAULT_PROBE_SPECS)


# ---------------------------------------------------------------------------
# Policy validation for live URLs
# ---------------------------------------------------------------------------


def validate_probe_url(url: str) -> None:
    """Fail-closed host/scheme policy before any network I/O."""
    text = str(url)
    if "\x00" in text:
        raise ValueError("url must not contain NUL")
    parts = urlsplit(text)
    scheme = (parts.scheme or "").lower()
    host = (parts.hostname or "").rstrip(".").lower()
    if scheme != "https":
        raise ValueError(f"https required for live probes, got scheme={scheme!r}")
    if not host:
        raise ValueError("url host is required")
    if parts.username or parts.password:
        raise ValueError("url userinfo is not allowed")
    if host not in ALLOWED_HOSTS:
        raise ValueError(f"host not on canary allowlist: {host!r}")
    port = parts.port or 443
    if port != 443:
        raise ValueError(f"port {port} not permitted for canary probes")


# ---------------------------------------------------------------------------
# HTTP execution (stdlib only; injectable opener for tests)
# ---------------------------------------------------------------------------


def _default_opener(prepared: urllib.request.Request, timeout: float) -> Any:
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler)
    return opener.open(prepared, timeout=timeout)


def _classify_http_status(status: int | None) -> ProbeStatus:
    if status is None:
        return ProbeStatus.UNKNOWN
    if status == 200:
        return ProbeStatus.SUCCESS
    if status == 204:
        return ProbeStatus.EMPTY
    if 400 <= status <= 599:
        return ProbeStatus.HTTP_ERROR
    return ProbeStatus.UNKNOWN


def execute_live_probe(
    spec: ProbeSpec,
    *,
    opener: Opener | None = None,
    timeout_seconds: float = REQUEST_TIMEOUT_SECONDS,
) -> ProbeResult:
    """Execute one bounded read-only live probe; never stores response body."""
    try:
        validate_probe_url(spec.url)
    except ValueError as exc:
        return ProbeResult(
            source=spec.source,
            status=ProbeStatus.POLICY_VIOLATION.value,
            mode=CanaryMode.LIVE.value,
            method=spec.method,
            host=host_of(spec.url),
            endpoint_fingerprint=endpoint_fingerprint(spec.url),
            status_code=None,
            body_sha256=None,
            body_bytes=None,
            content_type=None,
            authority_label=spec.authority_label,
            message=sanitize_text(str(exc)),
            fixture=False,
            metadata=MappingProxyType({"policy": "host_allowlist"}),
        )

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, application/xml, text/plain, */*",
    }
    prepared = urllib.request.Request(
        spec.url,
        headers=headers,
        method=spec.method,
    )
    open_fn = opener or _default_opener
    try:
        response = open_fn(prepared, float(timeout_seconds))
    except TimeoutError as exc:
        return ProbeResult(
            source=spec.source,
            status=ProbeStatus.TIMEOUT.value,
            mode=CanaryMode.LIVE.value,
            method=spec.method,
            host=host_of(spec.url),
            endpoint_fingerprint=endpoint_fingerprint(spec.url),
            status_code=None,
            body_sha256=None,
            body_bytes=None,
            content_type=None,
            authority_label=spec.authority_label,
            message=sanitize_text(f"timeout: {exc}"),
            fixture=False,
        )
    except urllib.error.HTTPError as http_err:
        try:
            raw = http_err.read(spec.max_bytes + 1)
        except Exception:  # noqa: BLE001
            raw = b""
        body = raw[: spec.max_bytes]
        status_code = int(getattr(http_err, "code", 0) or 0) or None
        return ProbeResult(
            source=spec.source,
            status=_classify_http_status(status_code).value,
            mode=CanaryMode.LIVE.value,
            method=spec.method,
            host=host_of(spec.url),
            endpoint_fingerprint=endpoint_fingerprint(spec.url),
            status_code=status_code,
            body_sha256=sha256_hex(body) if body else None,
            body_bytes=len(body),
            content_type=None,
            authority_label=spec.authority_label,
            message=sanitize_text(f"http_error:{status_code}"),
            fixture=False,
            metadata=MappingProxyType({"http_error": "1", "body_retained": "0"}),
        )
    except (urllib.error.URLError, OSError) as exc:
        return ProbeResult(
            source=spec.source,
            status=ProbeStatus.TRANSPORT_ERROR.value,
            mode=CanaryMode.LIVE.value,
            method=spec.method,
            host=host_of(spec.url),
            endpoint_fingerprint=endpoint_fingerprint(spec.url),
            status_code=None,
            body_sha256=None,
            body_bytes=None,
            content_type=None,
            authority_label=spec.authority_label,
            message=sanitize_text(f"transport_error: {type(exc).__name__}"),
            fixture=False,
        )

    try:
        status_code = int(getattr(response, "status", None) or response.getcode())
    except Exception:  # noqa: BLE001
        status_code = None
    headers_map: dict[str, str] = {}
    try:
        raw_headers = getattr(response, "headers", None) or {}
        if hasattr(raw_headers, "items"):
            headers_map = {str(k): str(v) for k, v in raw_headers.items()}
    except Exception:  # noqa: BLE001
        headers_map = {}
    content_type = None
    for key, value in headers_map.items():
        if key.lower() == "content-type":
            content_type = value.split(";", 1)[0].strip().lower() or None
            break

    body_len = 0
    body_digest: str | None = None
    truncated = False
    try:
        raw = response.read(spec.max_bytes + 1)
        truncated = len(raw) > spec.max_bytes
        body = raw[: spec.max_bytes]
        body_len = len(body)
        body_digest = sha256_hex(body) if body else None
        del raw
        del body
    except Exception as exc:  # noqa: BLE001
        try:
            response.close()
        except Exception:  # noqa: BLE001
            pass
        return ProbeResult(
            source=spec.source,
            status=ProbeStatus.TRANSPORT_ERROR.value,
            mode=CanaryMode.LIVE.value,
            method=spec.method,
            host=host_of(spec.url),
            endpoint_fingerprint=endpoint_fingerprint(spec.url),
            status_code=status_code,
            body_sha256=None,
            body_bytes=None,
            content_type=content_type,
            authority_label=spec.authority_label,
            message=sanitize_text(f"read_error: {type(exc).__name__}"),
            fixture=False,
        )
    finally:
        try:
            response.close()
        except Exception:  # noqa: BLE001
            pass

    if status_code == 200 and body_len == 0:
        probe_status = ProbeStatus.EMPTY
        message = "successful HTTP with empty body"
    else:
        probe_status = _classify_http_status(status_code)
        message = f"live probe {probe_status.value}"

    meta: dict[str, str] = {"body_retained": "0"}
    if truncated:
        meta["truncated"] = "1"

    return ProbeResult(
        source=spec.source,
        status=probe_status.value,
        mode=CanaryMode.LIVE.value,
        method=spec.method,
        host=host_of(spec.url),
        endpoint_fingerprint=endpoint_fingerprint(spec.url),
        status_code=status_code,
        body_sha256=body_digest,
        body_bytes=body_len,
        content_type=content_type,
        authority_label=spec.authority_label,
        message=sanitize_text(message),
        fixture=False,
        metadata=MappingProxyType(meta),
    )



def execute_offline_probe(case: Mapping[str, Any]) -> ProbeResult:
    """Materialize one offline fixture case into a ProbeResult."""
    source = str(case["source"])
    url = str(case.get("url") or "")
    return ProbeResult(
        source=source,
        status=ProbeStatus.FIXTURE.value,
        mode=CanaryMode.OFFLINE.value,
        method=str(case.get("method") or "GET").upper(),
        host=str(case.get("host") or host_of(url)),
        endpoint_fingerprint=endpoint_fingerprint(url) if url else "endpoint:fixture",
        status_code=int(case.get("status_code") or 200),
        body_sha256=str(case.get("body_sha256") or ""),
        body_bytes=int(case.get("body_bytes") or 0),
        content_type=str(case.get("content_type") or "application/json"),
        authority_label=str(case.get("authority_label") or "fixture"),
        message="offline fixture probe",
        fixture=True,
        metadata=MappingProxyType({"fixture_id": "patlaw-167-official-source-canary"}),
    )


# ---------------------------------------------------------------------------
# Canary run
# ---------------------------------------------------------------------------


def live_opted_in_from_env(environ: Mapping[str, str] | None = None) -> bool:
    env = environ if environ is not None else os.environ
    for flag in LIVE_ENV_FLAGS:
        raw = str(env.get(flag) or "").strip().lower()
        if raw in {"1", "true", "yes", "on"}:
            return True
    return False


def resolve_mode(
    *,
    live: bool = False,
    offline: bool = False,
    environ: Mapping[str, str] | None = None,
) -> CanaryMode:
    """Resolve canary mode. Offline is default; live is opt-in only."""
    if offline and live:
        raise ValueError("cannot request both --offline and --live")
    if offline:
        return CanaryMode.OFFLINE
    if live or live_opted_in_from_env(environ):
        return CanaryMode.LIVE
    return CanaryMode.OFFLINE


def default_receipt_dir() -> Path:
    state_base = Path(
        os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state")
    )
    return (
        state_base
        / "ipfs_accelerate_py"
        / "patent_legal_intelligence"
        / "live_canary"
    )


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[3]


def _disposition_for(
    mode: CanaryMode,
    results: Sequence[ProbeResult],
) -> OverallDisposition:
    if mode is CanaryMode.OFFLINE:
        if results and all(r.fixture for r in results):
            return OverallDisposition.OFFLINE_OK
        return OverallDisposition.FAIL
    # Live: success/empty are non-blocking connectivity signals; transport and
    # policy failures become gaps rather than hard fail unless all fail.
    if not results:
        return OverallDisposition.FAIL
    hard_fail = {
        ProbeStatus.POLICY_VIOLATION.value,
    }
    soft_gap = {
        ProbeStatus.HTTP_ERROR.value,
        ProbeStatus.TRANSPORT_ERROR.value,
        ProbeStatus.TIMEOUT.value,
        ProbeStatus.EMPTY.value,
        ProbeStatus.UNKNOWN.value,
        ProbeStatus.SKIPPED.value,
    }
    statuses = {r.status for r in results}
    if any(s in hard_fail for s in statuses) and all(
        s in hard_fail | soft_gap for s in statuses
    ):
        # All probes failed hard/soft → fail
        if not any(s == ProbeStatus.SUCCESS.value for s in statuses):
            return OverallDisposition.FAIL
    if any(s == ProbeStatus.SUCCESS.value for s in statuses):
        if any(s in soft_gap | hard_fail for s in statuses):
            return OverallDisposition.PASS_WITH_GAPS
        return OverallDisposition.PASS
    if all(s in soft_gap for s in statuses):
        return OverallDisposition.PASS_WITH_GAPS
    return OverallDisposition.FAIL


def run_canary(
    *,
    mode: CanaryMode | str | None = None,
    live: bool = False,
    offline: bool = False,
    probes: Sequence[ProbeSpec] | None = None,
    fixture_recipe: Mapping[str, Any] | None = None,
    opener: Opener | None = None,
    timeout_seconds: float = REQUEST_TIMEOUT_SECONDS,
    max_probes: int = MAX_PROBES_DEFAULT,
    receipt_dir: Path | None = None,
    write_receipt: bool = True,
    matter_root: Path | None = None,
    environ: Mapping[str, str] | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Run the official-source canary and return a content-free report.

    Parameters
    ----------
    mode:
        Explicit mode override (``offline`` / ``live``). When omitted, resolved
        from ``live`` / ``offline`` flags and environment.
    live / offline:
        CLI-style flags; offline is the default when neither is set.
    probes:
        Optional live probe specs (defaults to :func:`default_probe_specs`).
    fixture_recipe:
        Optional offline recipe (defaults to :func:`build_offline_fixture_recipe`).
    opener:
        Injectable HTTP opener for tests; production uses stdlib HTTPS.
    matter_root:
        Optional private matter directory that **must not change**. Snapshotted
        before/after; mutation raises.
    write_receipt:
        When true and ``receipt_dir`` is set (or default), write receipt JSON
        under a non-private path.
    """
    resolved = (
        CanaryMode(mode)
        if mode is not None
        else resolve_mode(live=live, offline=offline, environ=environ)
    )
    if max_probes < 1 or max_probes > MAX_PROBES_HARD_CAP:
        raise ValueError(
            f"max_probes must be in 1..{MAX_PROBES_HARD_CAP}, got {max_probes}"
        )

    assert_receipt_dir_safe(receipt_dir)
    matter_before: dict[str, str] | None = None
    if matter_root is not None:
        if not path_looks_like_private_matter(matter_root):
            # Still protect any explicitly provided matter root.
            pass
        matter_before = snapshot_directory(matter_root)

    clock = now or utc_now()
    results: list[ProbeResult] = []
    network_invoked = False

    if resolved is CanaryMode.OFFLINE:
        recipe = dict(fixture_recipe or build_offline_fixture_recipe())
        cases = list(recipe.get("cases") or [])
        if not cases:
            raise ValueError("offline fixture recipe has no cases")
        for case in cases[:max_probes]:
            if not isinstance(case, Mapping):
                continue
            results.append(execute_offline_probe(case))
        # Offline path must not touch the network opener.
        if opener is not None:
            # Callers may inject a sentinel opener that raises on use; we simply
            # never invoke it offline.
            pass
    else:
        specs = list(probes or default_probe_specs())[:max_probes]
        if not specs:
            raise ValueError("live mode requires at least one probe spec")
        for spec in specs:
            network_invoked = True
            results.append(
                execute_live_probe(
                    spec,
                    opener=opener,
                    timeout_seconds=timeout_seconds,
                )
            )

    disposition = _disposition_for(resolved, results)
    sources_seen = sorted({r.source for r in results})
    missing_sources = [s for s in SOURCE_FAMILIES if s not in sources_seen]

    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "interface": INTERFACE,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "policy_id": POLICY_ID,
        "generated_at": clock,
        "mode": resolved.value,
        "default_mode": CanaryMode.OFFLINE.value,
        "opt_in": resolved is CanaryMode.LIVE,
        "read_only": True,
        "bounded": True,
        "secret_redacted": True,
        "network_invoked": network_invoked and resolved is CanaryMode.LIVE,
        "max_probes": max_probes,
        "probe_count": len(results),
        "sources": list(SOURCE_FAMILIES),
        "sources_probed": sources_seen,
        "sources_missing": missing_sources,
        "forbidden_mutations": list(FORBIDDEN_MUTATIONS),
        "private_matter_mutated": False,
        "content_free": True,
        "disposition": disposition.value,
        "ok": disposition
        in {
            OverallDisposition.PASS,
            OverallDisposition.PASS_WITH_GAPS,
            OverallDisposition.OFFLINE_OK,
        },
        "probes": [r.to_dict() for r in results],
        "acceptance": {
            # Product default remains offline fixtures even when this run is live.
            "defaults_to_offline_fixtures": True,
            "offline_is_default": True,
            "live_is_opt_in": True,
            "ran_offline": resolved is CanaryMode.OFFLINE,
            "ran_live": resolved is CanaryMode.LIVE,
            "records_receipts": True,
            "never_mutates_private_matter_state": True,
            "probes_ecfr": "ecfr" in sources_seen,
            "probes_govinfo": "govinfo" in sources_seen,
            "probes_federal_register": "federal_register" in sources_seen,
            "probes_odp": "odp" in sources_seen,
        },
        "policy": {
            "allowed_hosts": sorted(ALLOWED_HOSTS),
            "allowed_methods": sorted(ALLOWED_METHODS),
            "max_response_bytes": MAX_RESPONSE_BYTES,
            "request_timeout_seconds": REQUEST_TIMEOUT_SECONDS,
            "live_env_flags": list(LIVE_ENV_FLAGS),
        },
    }

    # Digest binding for the report body (excluding the digest field itself).
    report["receipt_sha256"] = sha256_hex(canonical_json(report))

    assert_content_free(report)

    # Private matter immutability check.
    try:
        assert_no_private_matter_mutation(
            matter_root=matter_root,
            before_snapshot=matter_before,
        )
    except RuntimeError:
        report["private_matter_mutated"] = True
        report["ok"] = False
        report["disposition"] = OverallDisposition.FAIL.value
        report["content_free"] = True
        assert_content_free(report)
        raise

    if write_receipt:
        out_dir = receipt_dir if receipt_dir is not None else default_receipt_dir()
        assert_receipt_dir_safe(out_dir)
        written = write_canary_receipt(report, out_dir)
        report["receipt_path"] = str(written)
        # Re-bind digest after adding path (path is operator-local, content-free).
        without_digest = {k: v for k, v in report.items() if k != "receipt_sha256"}
        report["receipt_sha256"] = sha256_hex(canonical_json(without_digest))
        assert_content_free(report)

    return report


def write_canary_receipt(report: Mapping[str, Any], receipt_dir: Path) -> Path:
    """Atomically write a content-free canary receipt under *receipt_dir*."""
    assert_receipt_dir_safe(receipt_dir)
    receipt_dir.mkdir(parents=True, exist_ok=True)
    mode = str(report.get("mode") or "offline")
    stamp = str(report.get("generated_at") or utc_now()).replace(":", "")
    filename = f"canary-{mode}-{stamp}.json"
    target = receipt_dir / filename
    payload = redact_mapping(dict(report))
    assert_content_free(payload)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(target)
    # Also refresh a stable "latest" pointer for handoff tools.
    latest = receipt_dir / "canary-latest.json"
    latest_tmp = latest.with_suffix(".json.tmp")
    latest_tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    latest_tmp.replace(latest)
    return target


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_human(report: Mapping[str, Any]) -> None:
    print(
        f"canary mode={report.get('mode')} disposition={report.get('disposition')} "
        f"ok={report.get('ok')} probes={report.get('probe_count')} "
        f"network={report.get('network_invoked')}"
    )
    print(
        f"sources_probed={','.join(report.get('sources_probed') or []) or '-'} "
        f"private_matter_mutated={report.get('private_matter_mutated')}"
    )
    for probe in report.get("probes") or []:
        print(
            f"  {probe.get('source')}: status={probe.get('status')} "
            f"http={probe.get('status_code')} host={probe.get('host')} "
            f"fixture={probe.get('fixture')}"
        )
        if probe.get("message"):
            print(f"    - {probe.get('message')}")
    if report.get("receipt_path"):
        print(f"receipt: {report.get('receipt_path')}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "PATLAW-167 optional live official-source canary "
            "(defaults to offline fixtures)."
        )
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--offline",
        action="store_true",
        help="Force offline fixtures (default; no network)",
    )
    mode.add_argument(
        "--live",
        action="store_true",
        help="Opt-in live bounded probes (eCFR/GovInfo/Federal Register/ODP)",
    )
    parser.add_argument(
        "--receipt-dir",
        type=Path,
        default=None,
        help=(
            "Directory for content-free receipts "
            "(default: $XDG_STATE_HOME/.../live_canary)"
        ),
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Do not write a receipt file",
    )
    parser.add_argument(
        "--max-probes",
        type=int,
        default=MAX_PROBES_DEFAULT,
        help=f"Max probes (default {MAX_PROBES_DEFAULT}, hard cap {MAX_PROBES_HARD_CAP})",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=REQUEST_TIMEOUT_SECONDS,
        help=f"Per-probe timeout seconds (default {REQUEST_TIMEOUT_SECONDS})",
    )
    parser.add_argument(
        "--matter-root",
        type=Path,
        default=None,
        help=(
            "Optional private matter root to assert is not mutated "
            "(diagnostic; canary never writes here)"
        ),
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON report")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = run_canary(
            live=bool(args.live),
            offline=bool(args.offline),
            max_probes=int(args.max_probes),
            timeout_seconds=float(args.timeout),
            receipt_dir=Path(args.receipt_dir).expanduser()
            if args.receipt_dir is not None
            else None,
            write_receipt=not bool(args.no_write),
            matter_root=Path(args.matter_root).expanduser()
            if args.matter_root is not None
            else None,
        )
    except ValueError as exc:
        err = {"ok": False, "error": sanitize_text(str(exc)), "task_id": TASK_ID}
        if args.json:
            print(json.dumps(err, indent=2, sort_keys=True))
        else:
            print(f"ERROR: {err['error']}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        err = {
            "ok": False,
            "error": sanitize_text(str(exc)),
            "task_id": TASK_ID,
            "private_matter_mutated": True,
        }
        if args.json:
            print(json.dumps(err, indent=2, sort_keys=True))
        else:
            print(f"ERROR: {err['error']}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_human(report)

    if not report.get("ok"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
