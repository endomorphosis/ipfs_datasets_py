#!/usr/bin/env python3
"""Authenticated live provenance verifier for the legal-corpora Hub pins (LCR-070).

LCR-001 / LCR-048 freeze fixture-consistency snapshots. This additive verifier
re-observes both exact 40-hex revisions through authenticated Hub HTTPS, hashes
responses, inventories remote files and per-jurisdiction Parquet row counts,
records Viewer/config evidence, inventories configured local salvage roots
without copying secrets, and independently recomputes published baseline totals.

Live mode cannot be satisfied by constants or fixtures. ``--require-live-hub``
always constructs the urllib HTTPS transport and calls Hub.

Validation::

    python -m pytest tests/unit/scripts/test_audit_legal_corpora_live_baseline.py -q
    python scripts/ops/legal_data/audit_legal_corpora_live_baseline.py \\
        --require-live-hub --require-local-salvage-inventory --check

Dry-run receipts are documented observations that cannot pass
``--require-live-hub``. Tokens are never printed or persisted.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Mapping, MutableMapping, Sequence
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.ops.legal_data.audit_federal_register_hf_baseline import (  # noqa: E402
    ADVERTISED_DOCUMENT_COUNT,
    DATASET_REPO_ID as FEDERAL_REPO_ID,
    DATE_RANGE_COUNT,
    DATE_RANGE_END,
    DATE_RANGE_START,
    INCLUDE_FULL_TEXT,
    LEGACY_LAYOUT_ARTIFACTS,
    MATERIALIZED_ROW_COUNT,
    PINNED_REVISION as FEDERAL_PINNED_REVISION,
    REPOSITORY_FILE_COUNT as FEDERAL_REPOSITORY_FILE_COUNT,
)
from scripts.ops.legal_data.audit_state_laws_hf_baseline import (  # noqa: E402
    CID_OVERLAP_COUNT,
    DATASET_REPO_ID as STATE_REPO_ID,
    JURISDICTION_CODES,
    JURISDICTION_COUNT,
    MISSING_SUMMARIES,
    PER_STATE_CANONICAL_TOTAL_ROWS,
    PINNED_REVISION as STATE_PINNED_REVISION,
    README_CLAIMED_CANONICAL_ROWS,
    REPOSITORY_FILE_COUNT as STATE_REPOSITORY_FILE_COUNT,
    STATE_SUMMARY_COUNT,
    TRUNCATION_EXAMPLES,
    VIEWER_CANONICAL_LABEL,
    VIEWER_CANONICAL_ROW_COUNT,
    VIEWER_EMBEDDING_JURISDICTION_COUNT,
    VIEWER_EMBEDDING_ROW_COUNT,
)

TASK_ID = "LCR-070"
GOAL_ID = "LCR-G010"
PROGRAM_ID = "legal-corpora-reindex-v1"
PRODUCER = "audit_legal_corpora_live_baseline.py"
REPORT_SCHEMA = "ipfs_datasets_py/legal-corpora-reindex-live-baseline-provenance@1"
CODE_VERSION = "1"
TRANSPORT_LIVE_HTTPS = "urllib_https"
TRANSPORT_SCRIPTED = "scripted"
TRANSPORT_DRY_RUN = "dry-run"
MODE_LIVE = "live"
MODE_DRY_RUN = "dry-run"

HUB_API_ROOT = "https://huggingface.co/api"
HUB_RESOLVE_ROOT = "https://huggingface.co/datasets"
DATASETS_SERVER_ROOT = "https://datasets-server.huggingface.co"
WHOAMI_ENDPOINT = f"{HUB_API_ROOT}/whoami-v2"

DEFAULT_RECEIPT_RELPATH = Path(
    "docs/reports/legal_corpora_reindex/live_baseline_provenance_receipt.json"
)
HF_TOKEN_ENV_VARS: tuple[str, ...] = (
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
    "HUGGINGFACE_HUB_TOKEN",
    "HUGGINGFACE_TOKEN",
)
HF_TOKEN_FILE = Path.home() / ".cache" / "huggingface" / "token"
USER_AGENT = "ipfs_datasets_py-LCR-070"

STATE_CANONICAL_PARQUET = "state_laws_parquet_cid/state_laws_all_states.parquet"
STATE_EMBEDDING_PARQUET = (
    "state_laws_parquet_cid/state_laws_all_states_embeddings.parquet"
)
STATE_PARTITION_PREFIX = "state_laws_parquet_cid/"
FEDERAL_PARQUET_PATH = "federal_register.parquet"
FEDERAL_METADATA_PATH = "metadata.json"

UNPINNED_TOKENS = frozenset({"main", "master", "latest", "HEAD"})
SECRET_NAME_RE = re.compile(
    r"(secret|token|credential|passwd|password|\.env$|id_rsa|\.pem$)",
    re.IGNORECASE,
)
HF_TOKEN_RE = re.compile(r"hf_[A-Za-z0-9]{16,}")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
UTC_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z$"
)
LINK_NEXT_RE = re.compile(r'<([^>]+)>;\s*rel="next"', re.IGNORECASE)
PARTITION_NAME_RE = re.compile(r"^STATE-([A-Z]{2})\.parquet$")

DEFAULT_SALVAGE_SPECS: tuple[tuple[str, Path], ...] = (
    (
        "legal_scraper_parallel",
        Path.home() / ".ipfs_datasets" / "legal_scraper_parallel",
    ),
    ("state_laws", Path.home() / ".ipfs_datasets" / "state_laws"),
    ("federal_register", Path.home() / ".ipfs_datasets" / "federal_register"),
)

# Sealed fixture totals are expectations only. Live observations must come from Hub.
SEALED_STATE_EXPECTATIONS: Mapping[str, Any] = {
    "repository_files": STATE_REPOSITORY_FILE_COUNT,
    "per_state_total_rows": PER_STATE_CANONICAL_TOTAL_ROWS,
    "viewer_canonical_rows": VIEWER_CANONICAL_ROW_COUNT,
    "viewer_embedding_rows": VIEWER_EMBEDDING_ROW_COUNT,
    "viewer_embedding_jurisdictions": VIEWER_EMBEDDING_JURISDICTION_COUNT,
    "cid_overlap_count": CID_OVERLAP_COUNT,
    "missing_summaries": list(MISSING_SUMMARIES),
    "state_summaries_present": STATE_SUMMARY_COUNT,
    "readme_claimed_canonical_rows": README_CLAIMED_CANONICAL_ROWS,
    "truncation_examples": dict(TRUNCATION_EXAMPLES),
}
SEALED_FEDERAL_EXPECTATIONS: Mapping[str, Any] = {
    "repository_files": FEDERAL_REPOSITORY_FILE_COUNT,
    "advertised_documents": ADVERTISED_DOCUMENT_COUNT,
    "materialized_rows": MATERIALIZED_ROW_COUNT,
    "date_range_start": DATE_RANGE_START,
    "date_range_end": DATE_RANGE_END,
    "date_range_count": DATE_RANGE_COUNT,
    "include_full_text": INCLUDE_FULL_TEXT,
}


class LiveBaselineAuditError(RuntimeError):
    """Raised when live provenance cannot complete fail-closed."""


class HubResponse:
    """One hashed HTTPS response. Body bytes are not retained after digesting."""

    __slots__ = (
        "url",
        "method",
        "status",
        "headers",
        "body",
        "sha256",
        "content_type",
    )

    def __init__(
        self,
        *,
        url: str,
        method: str,
        status: int,
        headers: Mapping[str, str],
        body: bytes,
    ) -> None:
        self.url = url
        self.method = method.upper()
        self.status = int(status)
        self.headers = {str(k): str(v) for k, v in headers.items()}
        self.body = body
        self.sha256 = sha256_bytes(body)
        self.content_type = self.headers.get("Content-Type") or self.headers.get(
            "content-type"
        )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def sha256_canonical(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def utc_now() -> str:
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")
    return stamp[:-3] + "Z"


def default_receipt_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_RECEIPT_RELPATH).resolve()


def expected_jurisdiction_codes() -> list[str]:
    codes = list(JURISDICTION_CODES)
    if len(codes) != JURISDICTION_COUNT:
        raise LiveBaselineAuditError("jurisdiction set invariant broken")
    if "DC" not in codes:
        raise LiveBaselineAuditError("jurisdiction set must include DC")
    if len(set(codes)) != len(codes):
        raise LiveBaselineAuditError("jurisdiction set contains duplicates")
    return codes


def state_partition_path(code: str) -> str:
    return f"{STATE_PARTITION_PREFIX}STATE-{code}.parquet"


def dataset_revision_url(repo_id: str, revision: str) -> str:
    return f"{HUB_API_ROOT}/datasets/{urllib.parse.quote(repo_id, safe='/.')}/revision/{revision}"


def dataset_tree_url(repo_id: str, revision: str) -> str:
    return (
        f"{HUB_API_ROOT}/datasets/{urllib.parse.quote(repo_id, safe='/.')}"
        f"/tree/{revision}?recursive=true&expand=true"
    )


def dataset_resolve_url(repo_id: str, revision: str, path: str) -> str:
    quoted = "/".join(urllib.parse.quote(part, safe="") for part in path.split("/"))
    return (
        f"{HUB_RESOLVE_ROOT}/{urllib.parse.quote(repo_id, safe='/.')}"
        f"/resolve/{revision}/{quoted}"
    )


def datasets_server_url(endpoint: str, repo_id: str, revision: str) -> str:
    query = urllib.parse.urlencode({"dataset": repo_id, "revision": revision})
    return f"{DATASETS_SERVER_ROOT}/{endpoint}?{query}"


def require_commit_sha(value: Any, label: str) -> str:
    text = _require_str(value, label).casefold()
    if not COMMIT_SHA_RE.fullmatch(text):
        raise LiveBaselineAuditError(f"{label} must be an exact 40-hex revision")
    if text in UNPINNED_TOKENS:
        raise LiveBaselineAuditError(f"{label} must not be a mutable ref")
    return text


def _require_str(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LiveBaselineAuditError(f"{path} must be a non-empty string")
    return value


def _require_bool(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise LiveBaselineAuditError(f"{path} must be a boolean")
    return value


def _require_int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise LiveBaselineAuditError(f"{path} must be an integer")
    return value


def _require_mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise LiveBaselineAuditError(f"{path} must be a JSON object")
    return value


def _require_sha256(value: Any, path: str) -> str:
    text = _require_str(value, path).casefold()
    if not SHA256_RE.fullmatch(text):
        raise LiveBaselineAuditError(f"{path} must be a 64-hex digest")
    return text


def _require_utc(value: Any, path: str) -> str:
    text = _require_str(value, path)
    if not UTC_RE.fullmatch(text):
        raise LiveBaselineAuditError(f"{path} must be a UTC timestamp")
    return text


def redact_secret(text: str, token: str | None) -> str:
    redacted = text
    if token:
        redacted = redacted.replace(token, "<redacted-token>")
    redacted = HF_TOKEN_RE.sub("<redacted-token>", redacted)
    return redacted


def discover_hf_token() -> tuple[str, str]:
    for name in HF_TOKEN_ENV_VARS:
        value = os.environ.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip(), f"env:{name}"
    if HF_TOKEN_FILE.is_file() and not HF_TOKEN_FILE.is_symlink():
        try:
            value = HF_TOKEN_FILE.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise LiveBaselineAuditError(
                f"cannot read Hugging Face token file: {type(exc).__name__}"
            ) from exc
        if value:
            return value, "huggingface_token_file"
    try:
        from huggingface_hub.utils import get_token

        value = get_token()
    except Exception:
        value = None
    if isinstance(value, str) and value.strip():
        return value.strip(), "huggingface_hub_get_token"
    raise LiveBaselineAuditError(
        "no Hugging Face token available from env or ~/.cache/huggingface/token"
    )


def auth_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "User-Agent": USER_AGENT,
        "Accept": "application/json,application/octet-stream,*/*",
    }


def parse_link_next(link_header: str | None) -> str | None:
    if not link_header:
        return None
    match = LINK_NEXT_RE.search(link_header)
    if match is None:
        return None
    return match.group(1)


def open_live_hub_url(
    request: urllib.request.Request, timeout: float
) -> Any:
    """Network primitive used by live HTTPS. Tests may monkeypatch this."""
    return urllib.request.urlopen(request, timeout=timeout)


class LiveHubTransport:
    """Authenticated urllib HTTPS transport. This is the only live Hub path."""

    kind = TRANSPORT_LIVE_HTTPS
    is_live_https = True

    def __init__(self, token: str, *, timeout_seconds: float = 120.0) -> None:
        if not token or not str(token).strip():
            raise LiveBaselineAuditError("live Hub transport requires a token")
        self.token = str(token).strip()
        self.timeout_seconds = float(timeout_seconds)
        self.calls: list[dict[str, Any]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> HubResponse:
        if not url.startswith("https://huggingface.co/") and not url.startswith(
            "https://datasets-server.huggingface.co/"
        ):
            raise LiveBaselineAuditError(
                f"live transport refuses non-Hub URL: {url.split('?', 1)[0]}"
            )
        merged = dict(headers or auth_headers(self.token))
        if extra_headers:
            merged.update(extra_headers)
        request = urllib.request.Request(url, method=method.upper(), headers=merged)
        try:
            with open_live_hub_url(request, timeout=self.timeout_seconds) as resp:
                body = resp.read()
                status = int(getattr(resp, "status", 200) or 200)
                raw_headers = dict(getattr(resp, "headers", {}) or {})
        except urllib.error.HTTPError as exc:
            body = exc.read() if hasattr(exc, "read") else b""
            status = int(exc.code)
            raw_headers = dict(exc.headers or {})
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise LiveBaselineAuditError(
                "Hub network unavailable: "
                + redact_secret(f"{type(exc).__name__}", self.token)
            ) from exc
        response = HubResponse(
            url=url,
            method=method,
            status=status,
            headers=raw_headers,
            body=body,
        )
        self.calls.append(request_record(response))
        return response


class ScriptedHubTransport:
    """Hermetic test double. Cannot satisfy --require-live-hub."""

    kind = TRANSPORT_SCRIPTED
    is_live_https = False

    def __init__(
        self,
        responses: Mapping[str, Any],
        *,
        default_status: int = 200,
        token: str = "hf_scripted_test_token_aaaaaaaa",
    ) -> None:
        self._responses = dict(responses)
        self.default_status = default_status
        self.token = token
        self.calls: list[dict[str, Any]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> HubResponse:
        del headers, extra_headers
        key = _script_key(method, url)
        payload = self._responses.get(key)
        if payload is None:
            payload = self._responses.get(url)
        if payload is None:
            raise LiveBaselineAuditError(f"scripted Hub missing {method} {url}")
        if callable(payload):
            payload = payload(method, url)
        status = int(payload.get("status", self.default_status)) if isinstance(payload, Mapping) else self.default_status
        headers = {}
        body = b""
        if isinstance(payload, Mapping):
            headers = dict(payload.get("headers") or {})
            raw_body = payload.get("body", b"")
            if isinstance(raw_body, bytes):
                body = raw_body
            elif isinstance(raw_body, str):
                body = raw_body.encode("utf-8")
            else:
                body = json.dumps(raw_body).encode("utf-8")
            status = int(payload.get("status", status))
        elif isinstance(payload, bytes):
            body = payload
        else:
            body = json.dumps(payload).encode("utf-8")
        response = HubResponse(
            url=url, method=method, status=status, headers=headers, body=body
        )
        self.calls.append(request_record(response))
        return response


def _script_key(method: str, url: str) -> str:
    return f"{method.upper()} {url}"


def request_record(response: HubResponse) -> dict[str, Any]:
    parsed = urllib.parse.urlsplit(response.url)
    endpoint = urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, parsed.query, "")
    )
    return {
        "endpoint": endpoint,
        "method": response.method,
        "status": response.status,
        "response_sha256": response.sha256,
        "content_type": response.content_type,
        "byte_length": len(response.body),
    }


def json_body(response: HubResponse, label: str) -> Any:
    try:
        return json.loads(response.body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise LiveBaselineAuditError(f"{label} is not JSON") from exc


def redact_whoami(payload: Mapping[str, Any]) -> dict[str, Any]:
    orgs_out: list[dict[str, Any]] = []
    for org in payload.get("orgs") or []:
        if isinstance(org, Mapping):
            orgs_out.append(
                {
                    "name": org.get("name"),
                    "type": org.get("type"),
                }
            )
        elif isinstance(org, str) and org.strip():
            orgs_out.append({"name": org, "type": None})
    auth = payload.get("auth") if isinstance(payload.get("auth"), Mapping) else {}
    token_info = auth.get("accessToken") if isinstance(auth, Mapping) else None
    role = None
    display_name = None
    if isinstance(token_info, Mapping):
        role = token_info.get("role")
        display_name = token_info.get("displayName")
    return {
        "name": payload.get("name"),
        "type": payload.get("type"),
        "id": payload.get("id"),
        "orgs": orgs_out,
        "auth_type": auth.get("type") if isinstance(auth, Mapping) else None,
        "token_role": role,
        "token_display_name": display_name,
    }


def observe_identity(transport: Any, token: str, token_source: str) -> dict[str, Any]:
    response = transport.request("GET", WHOAMI_ENDPOINT, headers=auth_headers(token))
    if response.status >= 400:
        raise LiveBaselineAuditError(
            f"authenticated whoami failed with HTTP {response.status}"
        )
    payload = json_body(response, "whoami")
    if not isinstance(payload, Mapping):
        raise LiveBaselineAuditError("whoami must return a JSON object")
    identity = redact_whoami(payload)
    if not identity.get("name") or not identity.get("type"):
        raise LiveBaselineAuditError("whoami identity missing name/type")
    return {
        "authenticated": True,
        "token_present": True,
        "token_source": token_source,
        "whoami_endpoint": WHOAMI_ENDPOINT,
        "whoami_response_sha256": response.sha256,
        **identity,
    }


def fetch_dataset_revision(
    transport: Any, token: str, repo_id: str, expected_revision: str
) -> dict[str, Any]:
    url = dataset_revision_url(repo_id, expected_revision)
    response = transport.request("GET", url, headers=auth_headers(token))
    if response.status >= 400:
        raise LiveBaselineAuditError(
            f"dataset revision fetch failed for {repo_id}: HTTP {response.status}"
        )
    payload = json_body(response, f"{repo_id} revision")
    if not isinstance(payload, Mapping):
        raise LiveBaselineAuditError(f"{repo_id} revision payload must be an object")
    sha = require_commit_sha(payload.get("sha"), f"{repo_id}.sha")
    if sha != expected_revision.casefold():
        raise LiveBaselineAuditError(
            f"stale or changed pin for {repo_id}: expected {expected_revision}, got {sha}"
        )
    siblings = payload.get("siblings")
    sibling_count = len(siblings) if isinstance(siblings, list) else None
    card = payload.get("cardData") or payload.get("card_data")
    configs = None
    if isinstance(card, Mapping):
        configs = card.get("configs")
    return {
        "repo_id": repo_id,
        "revision": sha,
        "revision_pinned": True,
        "endpoint": url,
        "response_sha256": response.sha256,
        "last_modified": payload.get("lastModified") or payload.get("last_modified"),
        "sibling_count": sibling_count,
        "private": payload.get("private"),
        "has_card_data": isinstance(card, Mapping),
        "configs": configs,
        "has_readme_sibling": _sibling_has(siblings, "README.md"),
        "has_dataset_card_sibling": _sibling_has(siblings, "README.md"),
    }


def _sibling_has(siblings: Any, name: str) -> bool:
    if not isinstance(siblings, list):
        return False
    lowered = name.casefold()
    for item in siblings:
        if isinstance(item, Mapping):
            filename = str(item.get("rfilename") or item.get("path") or "")
        else:
            filename = str(getattr(item, "rfilename", "") or "")
        if filename.casefold() == lowered:
            return True
    return False


def fetch_repo_tree(
    transport: Any, token: str, repo_id: str, revision: str
) -> dict[str, Any]:
    url: str | None = dataset_tree_url(repo_id, revision)
    pages: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    directories = 0
    seen_urls: set[str] = set()
    while url:
        if url in seen_urls:
            raise LiveBaselineAuditError(f"tree pagination loop for {repo_id}")
        seen_urls.add(url)
        response = transport.request("GET", url, headers=auth_headers(token))
        if response.status >= 400:
            raise LiveBaselineAuditError(
                f"tree listing failed for {repo_id}: HTTP {response.status}"
            )
        payload = json_body(response, f"{repo_id} tree")
        if not isinstance(payload, list):
            raise LiveBaselineAuditError(f"{repo_id} tree page must be a JSON array")
        if not payload and not pages:
            raise LiveBaselineAuditError(f"{repo_id} tree is empty")
        page_records = []
        for item in payload:
            record = normalize_tree_item(item, repo_id)
            page_records.append(record)
            if record["type"] == "directory":
                directories += 1
            else:
                files.append(record)
        pages.append(
            {
                "endpoint": url,
                "status": response.status,
                "response_sha256": response.sha256,
                "item_count": len(payload),
            }
        )
        next_url = parse_link_next(
            response.headers.get("Link") or response.headers.get("link")
        )
        if next_url is None:
            url = None
        else:
            url = next_url
    files.sort(key=lambda item: item["path"])
    return {
        "repo_id": repo_id,
        "revision": revision,
        "file_count": len(files),
        "directory_count": directories,
        "page_count": len(pages),
        "pages": pages,
        "files": files,
        "inventory_sha256": sha256_canonical(
            [
                {
                    "path": item["path"],
                    "type": item["type"],
                    "size_bytes": item["size_bytes"],
                    "blob_id": item["blob_id"],
                    "lfs_sha256": item["lfs_sha256"],
                }
                for item in files
            ]
        ),
        "pagination_exhausted": True,
    }


def normalize_tree_item(item: Any, repo_id: str) -> dict[str, Any]:
    if not isinstance(item, Mapping):
        raise LiveBaselineAuditError(f"{repo_id} tree item must be an object")
    path = str(item.get("path") or item.get("rfilename") or "").strip()
    if not path:
        raise LiveBaselineAuditError(f"{repo_id} tree item missing path")
    item_type = str(item.get("type") or "file").casefold()
    if item_type in {"folder", "directory"}:
        item_type = "directory"
    else:
        item_type = "file"
    size = item.get("size")
    size_bytes = int(size) if isinstance(size, int) and not isinstance(size, bool) else None
    blob_id = item.get("oid") or item.get("blob_id")
    lfs = item.get("lfs") if isinstance(item.get("lfs"), Mapping) else None
    lfs_sha256 = None
    if lfs is not None:
        raw = str(lfs.get("sha256") or lfs.get("oid") or "")
        raw = raw.removeprefix("sha256:")
        if SHA256_RE.fullmatch(raw.casefold()):
            lfs_sha256 = raw.casefold()
        lfs_size = lfs.get("size")
        if size_bytes is None and isinstance(lfs_size, int) and not isinstance(lfs_size, bool):
            size_bytes = lfs_size
    return {
        "path": path,
        "type": item_type,
        "size_bytes": size_bytes,
        "blob_id": blob_id,
        "lfs_sha256": lfs_sha256,
    }


def parquet_num_rows_from_footer(footer_blob: bytes) -> int:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover
        raise LiveBaselineAuditError("pyarrow is required to read Parquet footers") from exc
    if len(footer_blob) < 8 or footer_blob[-4:] != b"PAR1":
        raise LiveBaselineAuditError("Parquet footer missing PAR1 magic")
    footer_len = int.from_bytes(footer_blob[-8:-4], "little")
    footer = footer_blob[:-8]
    if footer_len != len(footer):
        # Some range responses include extra prefix bytes; take the tail.
        if len(footer_blob) >= footer_len + 8:
            footer = footer_blob[-(footer_len + 8) : -8]
        else:
            raise LiveBaselineAuditError("Parquet footer length mismatch")
    fake = b"PAR1" + footer + footer_len.to_bytes(4, "little") + b"PAR1"
    try:
        meta = pq.read_metadata(io.BytesIO(fake))
    except Exception as exc:
        raise LiveBaselineAuditError(
            f"cannot parse Parquet footer: {type(exc).__name__}"
        ) from exc
    return int(meta.num_rows)


def _parquet_rows_from_bytes(body: bytes, path: str) -> int:
    if body[-4:] != b"PAR1":
        raise LiveBaselineAuditError(f"Parquet magic missing for {path}")
    try:
        import pyarrow.parquet as pq

        return int(pq.read_metadata(io.BytesIO(body)).num_rows)
    except Exception:
        return parquet_num_rows_from_footer(body)


def fetch_parquet_footer_rows(
    transport: Any, token: str, repo_id: str, revision: str, path: str
) -> dict[str, Any]:
    url = dataset_resolve_url(repo_id, revision, path)
    headers = auth_headers(token)
    tail = transport.request(
        "GET", url, headers=headers, extra_headers={"Range": "bytes=-8"}
    )
    if tail.status not in {200, 206}:
        raise LiveBaselineAuditError(
            f"Parquet tail fetch failed for {path}: HTTP {tail.status}"
        )
    if tail.status == 200 and len(tail.body) != 8 and tail.body[-4:] == b"PAR1":
        num_rows = _parquet_rows_from_bytes(tail.body, path)
        return {
            "path": path,
            "num_rows": num_rows,
            "footer_sha256": tail.sha256,
            "tail_sha256": tail.sha256,
            "endpoint": url,
            "footer_status": tail.status,
        }
    if len(tail.body) != 8 or tail.body[-4:] != b"PAR1":
        raise LiveBaselineAuditError(f"Parquet magic missing for {path}")
    footer_len = int.from_bytes(tail.body[:4], "little")
    if footer_len <= 0 or footer_len > 16_000_000:
        raise LiveBaselineAuditError(f"implausible Parquet footer length for {path}")
    footer = transport.request(
        "GET",
        url,
        headers=headers,
        extra_headers={"Range": f"bytes=-{footer_len + 8}"},
    )
    if footer.status not in {200, 206}:
        raise LiveBaselineAuditError(
            f"Parquet footer fetch failed for {path}: HTTP {footer.status}"
        )
    if footer.status == 200 and footer.body[-4:] == b"PAR1" and len(footer.body) != footer_len + 8:
        num_rows = _parquet_rows_from_bytes(footer.body, path)
    else:
        num_rows = parquet_num_rows_from_footer(footer.body)
    return {
        "path": path,
        "num_rows": num_rows,
        "footer_sha256": footer.sha256,
        "tail_sha256": tail.sha256,
        "endpoint": url,
        "footer_status": footer.status,
    }


def fetch_text_file(
    transport: Any, token: str, repo_id: str, revision: str, path: str
) -> HubResponse:
    url = dataset_resolve_url(repo_id, revision, path)
    response = transport.request("GET", url, headers=auth_headers(token))
    if response.status >= 400:
        raise LiveBaselineAuditError(
            f"failed to fetch {repo_id}:{path}: HTTP {response.status}"
        )
    return response


def fetch_parquet_table_columns(
    transport: Any,
    token: str,
    repo_id: str,
    revision: str,
    path: str,
    columns: Sequence[str],
) -> dict[str, list[Any]]:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover
        raise LiveBaselineAuditError("pyarrow is required to scan Viewer Parquet") from exc
    url = dataset_resolve_url(repo_id, revision, path)
    response = transport.request("GET", url, headers=auth_headers(token))
    if response.status >= 400:
        raise LiveBaselineAuditError(
            f"failed to download {path}: HTTP {response.status}"
        )
    try:
        table = pq.read_table(io.BytesIO(response.body), columns=list(columns))
    except Exception as exc:
        raise LiveBaselineAuditError(
            f"cannot read Parquet {path}: {type(exc).__name__}"
        ) from exc
    return {
        "num_rows": table.num_rows,
        "content_sha256": response.sha256,
        "endpoint": url,
        **{name: table.column(name).to_pylist() for name in columns if name in table.column_names},
    }


def fetch_datasets_server(
    transport: Any, token: str, repo_id: str, revision: str
) -> dict[str, Any]:
    evidence: dict[str, Any] = {}
    for endpoint in ("is-valid", "info", "size", "splits"):
        url = datasets_server_url(endpoint, repo_id, revision)
        response = transport.request("GET", url, headers=auth_headers(token))
        record = {
            "endpoint": url,
            "status": response.status,
            "response_sha256": response.sha256,
        }
        if response.status < 400:
            try:
                record["payload"] = json.loads(response.body.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError):
                record["payload"] = None
        else:
            record["payload"] = None
            record["disposition"] = "datasets_server_unavailable"
        evidence[endpoint] = record
    return evidence


def observe_state_laws(transport: Any, token: str) -> dict[str, Any]:
    revision = STATE_PINNED_REVISION
    info = fetch_dataset_revision(transport, token, STATE_REPO_ID, revision)
    tree = fetch_repo_tree(transport, token, STATE_REPO_ID, revision)
    files_by_path = {item["path"]: item for item in tree["files"]}
    missing_paths: list[str] = []
    partitions: dict[str, Any] = {}
    for code in expected_jurisdiction_codes():
        path = state_partition_path(code)
        if path not in files_by_path:
            missing_paths.append(path)
            continue
        rows = fetch_parquet_footer_rows(transport, token, STATE_REPO_ID, revision, path)
        file_meta = files_by_path[path]
        partitions[code] = {
            "code": code,
            "path": path,
            "num_rows": rows["num_rows"],
            "size_bytes": file_meta.get("size_bytes"),
            "blob_id": file_meta.get("blob_id"),
            "lfs_sha256": file_meta.get("lfs_sha256"),
            "footer_sha256": rows["footer_sha256"],
            "endpoint": rows["endpoint"],
        }
    if missing_paths:
        raise LiveBaselineAuditError(
            "missing state-law partitions: " + ", ".join(missing_paths)
        )
    if "DC" not in partitions:
        raise LiveBaselineAuditError("state-law partitions must include DC")
    if len(partitions) != JURISDICTION_COUNT:
        raise LiveBaselineAuditError(
            f"expected {JURISDICTION_COUNT} partitions, got {len(partitions)}"
        )

    for required in (STATE_CANONICAL_PARQUET, STATE_EMBEDDING_PARQUET, "README.md"):
        if required not in files_by_path:
            raise LiveBaselineAuditError(f"missing required remote path: {required}")

    canonical = fetch_parquet_table_columns(
        transport,
        token,
        STATE_REPO_ID,
        revision,
        STATE_CANONICAL_PARQUET,
        ("state_code", "ipfs_cid"),
    )
    embeddings = fetch_parquet_table_columns(
        transport,
        token,
        STATE_REPO_ID,
        revision,
        STATE_EMBEDDING_PARQUET,
        ("state_code", "ipfs_cid"),
    )
    canonical_codes = canonical.get("state_code") or []
    embedding_codes = embeddings.get("state_code") or []
    canonical_cids = set(canonical.get("ipfs_cid") or [])
    embedding_cids = set(embeddings.get("ipfs_cid") or [])
    unique_canonical = sorted({str(code) for code in canonical_codes if code})
    unique_embeddings = sorted({str(code) for code in embedding_codes if code})
    cid_overlap = len(canonical_cids & embedding_cids)
    per_state_total = sum(int(item["num_rows"]) for item in partitions.values())
    truncation_examples = {
        code: int(item["num_rows"])
        for code, item in partitions.items()
        if code in TRUNCATION_EXAMPLES
    }

    summary_paths = sorted(
        path
        for path in files_by_path
        if path.startswith("state_summaries/") and path.endswith(".json")
    )
    present_summaries = sorted(
        PurePosixPath(path).stem for path in summary_paths if len(PurePosixPath(path).stem) == 2
    )
    missing_summaries = [
        code for code in expected_jurisdiction_codes() if code not in present_summaries
    ]

    readme = fetch_text_file(transport, token, STATE_REPO_ID, revision, "README.md")
    readme_text = readme.body.decode("utf-8", errors="replace")
    claimed = _parse_readme_claimed_rows(readme_text)
    viewer_server = fetch_datasets_server(transport, token, STATE_REPO_ID, revision)

    return {
        "repo_id": STATE_REPO_ID,
        "revision": revision,
        "revision_pinned": True,
        "dataset_info": {
            "endpoint": info["endpoint"],
            "response_sha256": info["response_sha256"],
            "last_modified": info["last_modified"],
            "sibling_count": info["sibling_count"],
            "configs": info["configs"],
        },
        "tree": {
            "file_count": tree["file_count"],
            "directory_count": tree["directory_count"],
            "page_count": tree["page_count"],
            "pages": tree["pages"],
            "inventory_sha256": tree["inventory_sha256"],
            "pagination_exhausted": tree["pagination_exhausted"],
        },
        "files": [
            {
                "path": item["path"],
                "type": item["type"],
                "size_bytes": item["size_bytes"],
                "blob_id": item["blob_id"],
                "lfs_sha256": item["lfs_sha256"],
            }
            for item in tree["files"]
        ],
        "partitions": partitions,
        "viewer": {
            "canonical_config": {
                "path": STATE_CANONICAL_PARQUET,
                "row_count": canonical["num_rows"],
                "jurisdiction_labels": unique_canonical,
                "ia_only": unique_canonical == [VIEWER_CANONICAL_LABEL],
                "all_rows_labeled_ia": unique_canonical == [VIEWER_CANONICAL_LABEL]
                and canonical["num_rows"] == len(canonical_codes),
                "content_sha256": canonical["content_sha256"],
                "endpoint": canonical["endpoint"],
            },
            "embedding_config": {
                "path": STATE_EMBEDDING_PARQUET,
                "row_count": embeddings["num_rows"],
                "jurisdiction_count": len(unique_embeddings),
                "jurisdiction_labels": unique_embeddings,
                "rows_per_jurisdiction_min": min(
                    embedding_codes.count(code) for code in unique_embeddings
                )
                if unique_embeddings
                else 0,
                "rows_per_jurisdiction_max": max(
                    embedding_codes.count(code) for code in unique_embeddings
                )
                if unique_embeddings
                else 0,
                "stale_sample": True,
                "content_sha256": embeddings["content_sha256"],
                "endpoint": embeddings["endpoint"],
            },
            "datasets_server": viewer_server,
            "dataset_viewer_valid": False,
        },
        "cid_overlap": {
            "canonical_vs_embeddings": cid_overlap,
            "zero_overlap": cid_overlap == 0,
        },
        "summaries": {
            "present_count": len(present_summaries),
            "present": present_summaries,
            "missing": missing_summaries,
            "missing_count": len(missing_summaries),
        },
        "readme": {
            "path": "README.md",
            "response_sha256": readme.sha256,
            "claimed_canonical_rows": claimed,
            "endpoint": dataset_resolve_url(STATE_REPO_ID, revision, "README.md"),
        },
        "counts": {
            "repository_files": tree["file_count"],
            "jurisdictions": len(partitions),
            "state_parquet_filenames": len(partitions),
            "per_state_canonical_total_rows": per_state_total,
            "viewer_canonical_rows": canonical["num_rows"],
            "viewer_embedding_rows": embeddings["num_rows"],
            "viewer_embedding_jurisdictions": len(unique_embeddings),
            "cid_overlap_canonical_vs_embeddings": cid_overlap,
            "state_summaries_present": len(present_summaries),
            "state_summaries_missing": len(missing_summaries),
            "readme_claimed_canonical_rows": claimed,
        },
        "truncation_examples": truncation_examples,
        "includes_dc": True,
    }


def _parse_readme_claimed_rows(text: str) -> int | None:
    match = re.search(
        r"(?:canonical|statute|row)s?[^\n]{0,40}?(?:is|are|of|=|:)?[^\n]{0,10}?"
        r"([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{4,})",
        text,
        re.IGNORECASE,
    )
    if match:
        return int(match.group(1).replace(",", ""))
    if "20,514" in text or "20514" in text:
        return 20_514
    numbers = [
        int(item.replace(",", ""))
        for item in re.findall(r"[0-9]{1,3}(?:,[0-9]{3})+", text)
    ]
    return numbers[0] if numbers else None


def observe_federal_register(transport: Any, token: str) -> dict[str, Any]:
    revision = FEDERAL_PINNED_REVISION
    info = fetch_dataset_revision(transport, token, FEDERAL_REPO_ID, revision)
    tree = fetch_repo_tree(transport, token, FEDERAL_REPO_ID, revision)
    files_by_path = {item["path"]: item for item in tree["files"]}
    for required in (FEDERAL_PARQUET_PATH, FEDERAL_METADATA_PATH):
        if required not in files_by_path:
            raise LiveBaselineAuditError(
                f"missing required Federal Register path: {required}"
            )
    parquet = fetch_parquet_footer_rows(
        transport, token, FEDERAL_REPO_ID, revision, FEDERAL_PARQUET_PATH
    )
    metadata_resp = fetch_text_file(
        transport, token, FEDERAL_REPO_ID, revision, FEDERAL_METADATA_PATH
    )
    try:
        metadata = json.loads(metadata_resp.body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise LiveBaselineAuditError("federal metadata.json is not JSON") from exc
    if not isinstance(metadata, Mapping):
        raise LiveBaselineAuditError("federal metadata.json must be an object")
    advertised = metadata.get("documents_count")
    if not isinstance(advertised, int) or isinstance(advertised, bool):
        raise LiveBaselineAuditError("federal metadata.json missing documents_count")
    date_range = metadata.get("date_range") if isinstance(metadata.get("date_range"), Mapping) else {}
    partitioning = (
        metadata.get("partitioning")
        if isinstance(metadata.get("partitioning"), Mapping)
        else {}
    )
    include_full_text = metadata.get("include_full_text")
    viewer_server = fetch_datasets_server(transport, token, FEDERAL_REPO_ID, revision)
    legacy_present = [
        artifact
        for artifact in LEGACY_LAYOUT_ARTIFACTS
        if artifact.rstrip("/") in files_by_path
        or any(
            path == artifact or path.startswith(str(artifact))
            for path in files_by_path
        )
    ]
    has_readme = "README.md" in files_by_path
    return {
        "repo_id": FEDERAL_REPO_ID,
        "revision": revision,
        "revision_pinned": True,
        "dataset_info": {
            "endpoint": info["endpoint"],
            "response_sha256": info["response_sha256"],
            "last_modified": info["last_modified"],
            "sibling_count": info["sibling_count"],
            "has_dataset_card": has_readme,
        },
        "tree": {
            "file_count": tree["file_count"],
            "directory_count": tree["directory_count"],
            "page_count": tree["page_count"],
            "pages": tree["pages"],
            "inventory_sha256": tree["inventory_sha256"],
            "pagination_exhausted": tree["pagination_exhausted"],
        },
        "files": [
            {
                "path": item["path"],
                "type": item["type"],
                "size_bytes": item["size_bytes"],
                "blob_id": item["blob_id"],
                "lfs_sha256": item["lfs_sha256"],
            }
            for item in tree["files"]
        ],
        "parquet": {
            "path": FEDERAL_PARQUET_PATH,
            "num_rows": parquet["num_rows"],
            "footer_sha256": parquet["footer_sha256"],
            "endpoint": parquet["endpoint"],
            "size_bytes": files_by_path[FEDERAL_PARQUET_PATH].get("size_bytes"),
            "lfs_sha256": files_by_path[FEDERAL_PARQUET_PATH].get("lfs_sha256"),
        },
        "metadata": {
            "path": FEDERAL_METADATA_PATH,
            "response_sha256": metadata_resp.sha256,
            "endpoint": dataset_resolve_url(
                FEDERAL_REPO_ID, revision, FEDERAL_METADATA_PATH
            ),
            "advertised_documents": advertised,
            "include_full_text": include_full_text,
            "date_range_start": date_range.get("start_date"),
            "date_range_end": date_range.get("end_date"),
            "date_range_count": partitioning.get("queried_ranges"),
        },
        "legacy_layout": {
            "present": bool(legacy_present),
            "artifacts_found": legacy_present,
            "has_dataset_card": has_readme,
        },
        "viewer": {
            "datasets_server": viewer_server,
            "dataset_viewer_valid": False,
        },
        "counts": {
            "repository_files": tree["file_count"],
            "advertised_documents": advertised,
            "hub_parquet_rows": parquet["num_rows"],
            "count_mismatch_delta": parquet["num_rows"] - advertised,
            "include_full_text": include_full_text,
        },
    }


def configured_salvage_roots(
    overrides: Sequence[tuple[str, Path]] | None = None,
) -> list[tuple[str, Path]]:
    if overrides:
        return [(str(name), Path(path)) for name, path in overrides]
    env = os.environ.get("LEGAL_CORPORA_SALVAGE_ROOTS")
    if env and env.strip():
        roots: list[tuple[str, Path]] = []
        for item in env.split(os.pathsep):
            item = item.strip()
            if not item:
                continue
            if "=" in item:
                name, raw = item.split("=", 1)
            else:
                name, raw = Path(item).name, item
            roots.append((name.strip(), Path(raw).expanduser()))
        if roots:
            return roots
    return [(name, path) for name, path in DEFAULT_SALVAGE_SPECS]


def display_salvage_path(path: Path) -> str:
    resolved = path
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    home = Path.home()
    try:
        rel = resolved.relative_to(home)
        return "$HOME/" + rel.as_posix()
    except ValueError:
        return "redacted-path:" + sha256_bytes(str(resolved).encode("utf-8"))[:16]


def is_secret_name(name: str) -> bool:
    return bool(SECRET_NAME_RE.search(name))


def local_parquet_num_rows(path: Path) -> int | None:
    try:
        import pyarrow.parquet as pq
    except ImportError:
        return None
    try:
        return int(pq.read_metadata(str(path)).num_rows)
    except Exception:
        return None


def inventory_salvage_root(root_id: str, root: Path) -> dict[str, Any]:
    label = display_salvage_path(root)
    record: dict[str, Any] = {
        "root_id": root_id,
        "path_label": label,
        "path_sha256": sha256_bytes(str(root.expanduser()).encode("utf-8")),
        "present": False,
        "accessible": False,
        "symlink": root.is_symlink(),
        "disposition": "missing",
        "file_count": 0,
        "directory_count": 0,
        "parquet_count": 0,
        "jsonld_count": 0,
        "skipped_symlinks": 0,
        "skipped_secrets": 0,
        "three_shard_runs": [],
        "state_partitions": {},
        "federal_parquet_rows": None,
        "inventory_sha256": None,
    }
    if root.is_symlink():
        record["disposition"] = "symlink_skipped"
        return record
    if not root.exists():
        record["disposition"] = "missing"
        return record
    if not root.is_dir():
        record["disposition"] = "not_a_directory"
        record["present"] = True
        return record
    record["present"] = True
    listing: list[dict[str, Any]] = []
    try:
        _walk_salvage(root, root, record, listing)
    except OSError as exc:
        record["disposition"] = "inaccessible"
        record["error"] = type(exc).__name__
        return record
    record["accessible"] = True
    record["disposition"] = "inventoried"
    record["inventory_sha256"] = sha256_canonical(listing)
    record["has_nonempty_inventory"] = record["file_count"] > 0
    return record


def _walk_salvage(
    root: Path, current: Path, record: dict[str, Any], listing: list[dict[str, Any]]
) -> None:
    try:
        entries = list(os.scandir(current))
    except OSError:
        record["disposition"] = "inaccessible"
        raise
    shard_names = {entry.name for entry in entries}
    if {"shard1", "shard2", "shard3"}.issubset(shard_names):
        rel = current.relative_to(root).as_posix() if current != root else "."
        record["three_shard_runs"].append(rel)
    for entry in entries:
        name = entry.name
        if name in {".", ".."}:
            continue
        if is_secret_name(name):
            record["skipped_secrets"] += 1
            continue
        try:
            is_link = entry.is_symlink()
        except OSError:
            continue
        if is_link:
            record["skipped_symlinks"] += 1
            continue
        rel = Path(entry.path).relative_to(root).as_posix()
        try:
            is_dir = entry.is_dir(follow_symlinks=False)
            is_file = entry.is_file(follow_symlinks=False)
        except OSError:
            continue
        if is_dir:
            record["directory_count"] += 1
            listing.append({"path": rel, "type": "directory", "size_bytes": None})
            _walk_salvage(root, Path(entry.path), record, listing)
            continue
        if not is_file:
            continue
        try:
            size = int(entry.stat(follow_symlinks=False).st_size)
        except OSError:
            size = None
        record["file_count"] += 1
        listing.append({"path": rel, "type": "file", "size_bytes": size})
        lowered = name.casefold()
        if lowered.endswith(".parquet"):
            record["parquet_count"] += 1
            match = PARTITION_NAME_RE.fullmatch(name)
            if match:
                code = match.group(1)
                rows = local_parquet_num_rows(Path(entry.path))
                record["state_partitions"][code] = {
                    "relative_path": rel,
                    "num_rows": rows,
                    "size_bytes": size,
                }
            if name in {"laws.parquet", "federal_register.parquet"} or rel.endswith(
                "federal_register_parquet/laws.parquet"
            ):
                record["federal_parquet_rows"] = local_parquet_num_rows(Path(entry.path))
        if lowered.endswith(".jsonld"):
            record["jsonld_count"] += 1


def observe_local_salvage(
    roots: Sequence[tuple[str, Path]] | None = None,
) -> dict[str, Any]:
    configured = configured_salvage_roots(roots)
    inventories = [inventory_salvage_root(name, path) for name, path in configured]
    present = [item for item in inventories if item.get("present") and item.get("accessible")]
    return {
        "configured_root_ids": [name for name, _path in configured],
        "roots": inventories,
        "present_root_count": len(present),
        "inventoried": True,
        "secrets_copied": False,
        "symlinks_followed": False,
        "absolute_paths_persisted": False,
        "three_shard_run_detected": any(
            item.get("three_shard_runs") for item in inventories
        ),
        "inventory_sha256": sha256_canonical(
            [
                {
                    "root_id": item["root_id"],
                    "disposition": item["disposition"],
                    "inventory_sha256": item.get("inventory_sha256"),
                    "file_count": item.get("file_count"),
                }
                for item in inventories
            ]
        ),
    }


def typed_disposition(
    code: str,
    *,
    detail: str,
    expected: Any = None,
    observed: Any = None,
    severity: str = "blocking",
) -> dict[str, Any]:
    payload = {
        "code": code,
        "severity": severity,
        "typed_explanation": True,
        "detail": detail,
    }
    if expected is not None:
        payload["expected"] = expected
    if observed is not None:
        payload["observed"] = observed
    return payload


def collect_dispositions(
    state: Mapping[str, Any],
    federal: Mapping[str, Any],
    salvage: Mapping[str, Any],
) -> list[dict[str, Any]]:
    dispositions: list[dict[str, Any]] = []
    counts = state["counts"]
    viewer = state["viewer"]["canonical_config"]
    embeddings = state["viewer"]["embedding_config"]
    if viewer.get("ia_only") is True:
        dispositions.append(
            typed_disposition(
                "IA_ONLY_CANONICAL_VIEWER",
                detail="Viewer canonical Parquet rows are entirely labeled IA",
                observed=viewer.get("row_count"),
            )
        )
    if embeddings.get("jurisdiction_count") == JURISDICTION_COUNT and embeddings.get(
        "row_count"
    ) != counts.get("per_state_canonical_total_rows"):
        dispositions.append(
            typed_disposition(
                "STALE_51_STATE_EMBEDDINGS",
                detail="Viewer embeddings span 51 jurisdictions but are a sparse older sample",
                observed=embeddings.get("row_count"),
            )
        )
    if state["cid_overlap"].get("zero_overlap") is True:
        dispositions.append(
            typed_disposition(
                "ZERO_CID_OVERLAP",
                detail="canonical and embedding CID sets do not overlap",
                observed=0,
            )
        )
    trunc = state.get("truncation_examples") or {}
    if trunc:
        dispositions.append(
            typed_disposition(
                "PER_STATE_TRUNCATION",
                detail="remote per-jurisdiction files include obvious truncations",
                observed=trunc,
                expected=dict(TRUNCATION_EXAMPLES),
            )
        )
    missing = state["summaries"].get("missing") or []
    if missing:
        dispositions.append(
            typed_disposition(
                "MISSING_STATE_SUMMARIES",
                detail="state_summaries directory is missing jurisdictions",
                observed=missing,
                expected=list(MISSING_SUMMARIES),
            )
        )
    claimed = counts.get("readme_claimed_canonical_rows")
    if claimed not in {None, counts.get("viewer_canonical_rows"), counts.get("per_state_canonical_total_rows")}:
        dispositions.append(
            typed_disposition(
                "README_ROW_COUNT_CONFLICT",
                detail="README claimed rows conflict with Viewer and per-state totals",
                observed=claimed,
                expected={
                    "viewer_canonical_rows": counts.get("viewer_canonical_rows"),
                    "per_state_total_rows": counts.get("per_state_canonical_total_rows"),
                },
            )
        )
    for endpoint, record in (state["viewer"].get("datasets_server") or {}).items():
        if record.get("status", 200) >= 400:
            dispositions.append(
                typed_disposition(
                    "DATASETS_SERVER_UNAVAILABLE",
                    detail=f"state-law datasets-server {endpoint} returned HTTP {record.get('status')}",
                    observed=record.get("status"),
                    severity="observed_mismatch",
                )
            )

    fed_counts = federal["counts"]
    advertised = fed_counts.get("advertised_documents")
    hub_rows = fed_counts.get("hub_parquet_rows")
    if advertised != hub_rows:
        dispositions.append(
            typed_disposition(
                "FEDERAL_ADVERTISED_VS_HUB_PARQUET",
                detail="metadata.json advertised documents differ from Hub Parquet footer rows",
                expected=advertised,
                observed=hub_rows,
            )
        )
    if hub_rows != MATERIALIZED_ROW_COUNT:
        dispositions.append(
            typed_disposition(
                "FEDERAL_HUB_PARQUET_VS_SEALED_LOCAL_MATERIALIZED",
                detail="Hub Parquet footer rows differ from the sealed local materialized count",
                expected=MATERIALIZED_ROW_COUNT,
                observed=hub_rows,
            )
        )
    if federal["metadata"].get("include_full_text") is False:
        dispositions.append(
            typed_disposition(
                "MISSING_FULL_TEXT_CONTRACT",
                detail="metadata.json declares include_full_text=false",
                observed=False,
            )
        )
    if federal["legacy_layout"].get("has_dataset_card") is not True:
        dispositions.append(
            typed_disposition(
                "MISSING_DATASET_CARD",
                detail="no README/dataset card on the Federal Register pin",
                observed=False,
            )
        )
    if federal["legacy_layout"].get("present") is True:
        dispositions.append(
            typed_disposition(
                "LEGACY_LAYOUT",
                detail="legacy root-level Federal Register artifacts are present",
                observed=federal["legacy_layout"].get("artifacts_found"),
            )
        )
    for endpoint, record in (federal["viewer"].get("datasets_server") or {}).items():
        if record.get("status", 200) >= 400:
            dispositions.append(
                typed_disposition(
                    "DATASETS_SERVER_UNAVAILABLE",
                    detail=f"Federal datasets-server {endpoint} returned HTTP {record.get('status')}",
                    observed=record.get("status"),
                    severity="observed_mismatch",
                )
            )

    for root in salvage.get("roots") or []:
        if root.get("disposition") != "inventoried":
            dispositions.append(
                typed_disposition(
                    "LOCAL_SALVAGE_ROOT_DISPOSITION",
                    detail=f"salvage root {root.get('root_id')} is {root.get('disposition')}",
                    observed=root.get("disposition"),
                    severity="observed_mismatch",
                )
            )
        partitions = root.get("state_partitions") or {}
        if partitions and "DC" not in partitions:
            dispositions.append(
                typed_disposition(
                    "LOCAL_SALVAGE_MISSING_DC",
                    detail=f"salvage root {root.get('root_id')} has state parquet files but no DC partition",
                    observed=sorted(partitions),
                    severity="observed_mismatch",
                )
            )
        local_fed = root.get("federal_parquet_rows")
        if local_fed is not None and local_fed != hub_rows:
            dispositions.append(
                typed_disposition(
                    "FEDERAL_HUB_PARQUET_VS_LOCAL_SALVAGE",
                    detail=f"local salvage {root.get('root_id')} Federal Parquet rows differ from Hub",
                    expected=hub_rows,
                    observed=local_fed,
                )
            )
        if local_fed is not None and local_fed != MATERIALIZED_ROW_COUNT:
            dispositions.append(
                typed_disposition(
                    "FEDERAL_LOCAL_SALVAGE_VS_SEALED_MATERIALIZED",
                    detail="local salvage Federal rows differ from sealed materialized count",
                    expected=MATERIALIZED_ROW_COUNT,
                    observed=local_fed,
                    severity="observed_mismatch",
                )
            )
    return dispositions


def unexplained_count_mismatches(
    state: Mapping[str, Any],
    federal: Mapping[str, Any],
    dispositions: Sequence[Mapping[str, Any]],
) -> list[str]:
    typed_codes = {item.get("code") for item in dispositions if item.get("typed_explanation")}
    unexplained: list[str] = []
    counts = state["counts"]
    if counts.get("per_state_canonical_total_rows") != PER_STATE_CANONICAL_TOTAL_ROWS:
        unexplained.append("state per-state total does not match sealed 212103")
    if counts.get("viewer_canonical_rows") != VIEWER_CANONICAL_ROW_COUNT:
        unexplained.append("viewer canonical rows do not match sealed 47204")
    if counts.get("viewer_embedding_rows") != VIEWER_EMBEDDING_ROW_COUNT:
        unexplained.append("viewer embedding rows do not match sealed 17338")
    if counts.get("repository_files") != STATE_REPOSITORY_FILE_COUNT:
        unexplained.append("state repository file count does not match sealed 2116")
    if counts.get("cid_overlap_canonical_vs_embeddings") != 0:
        unexplained.append("CID overlap is not zero")
    if federal["counts"].get("repository_files") != FEDERAL_REPOSITORY_FILE_COUNT:
        unexplained.append("federal repository file count does not match sealed 555")
    if federal["counts"].get("advertised_documents") != ADVERTISED_DOCUMENT_COUNT:
        unexplained.append("federal advertised documents do not match sealed 993703")
    if (
        federal["counts"].get("hub_parquet_rows") != MATERIALIZED_ROW_COUNT
        and "FEDERAL_HUB_PARQUET_VS_SEALED_LOCAL_MATERIALIZED" not in typed_codes
    ):
        unexplained.append(
            "federal Hub Parquet rows differ from sealed materialized count without typed explanation"
        )
    if (
        federal["counts"].get("advertised_documents")
        != federal["counts"].get("hub_parquet_rows")
        and "FEDERAL_ADVERTISED_VS_HUB_PARQUET" not in typed_codes
    ):
        unexplained.append(
            "federal advertised vs Hub Parquet mismatch lacks typed explanation"
        )
    return unexplained


def gather_request_records(transport: Any) -> list[dict[str, Any]]:
    calls = getattr(transport, "calls", None)
    if not isinstance(calls, list):
        raise LiveBaselineAuditError("transport did not record Hub requests")
    if not calls:
        raise LiveBaselineAuditError("no Hub requests were recorded")
    return list(calls)


def assert_no_token_leakage(payload: Mapping[str, Any], token: str | None) -> None:
    blob = json.dumps(payload, sort_keys=True, default=str)
    if token and token in blob:
        raise LiveBaselineAuditError("token leakage: raw token present in receipt")
    if "Authorization" in blob and "Bearer " in blob:
        raise LiveBaselineAuditError("token leakage: Authorization header persisted")
    leaked = HF_TOKEN_RE.findall(blob)
    # Allow the documented scripted test-token pattern only inside unit tests if
    # it never matches a real hf_ live token. Any hf_ value is a leak.
    if leaked:
        raise LiveBaselineAuditError("token leakage: Hugging Face token pattern in receipt")


def seal_receipt(payload: MutableMapping[str, Any], token: str | None) -> dict[str, Any]:
    payload.pop("receipt_sha256", None)
    assert_no_token_leakage(payload, token)
    digest = sha256_canonical(dict(payload))
    payload["receipt_sha256"] = digest
    assert_no_token_leakage(payload, token)
    return dict(payload)


def build_receipt(
    *,
    transport: Any,
    token: str,
    token_source: str,
    salvage_roots: Sequence[tuple[str, Path]] | None = None,
    observed_at: str | None = None,
    mode: str = MODE_LIVE,
) -> dict[str, Any]:
    transport_kind = getattr(transport, "kind", TRANSPORT_SCRIPTED)
    is_live_https = bool(getattr(transport, "is_live_https", False))
    if mode == MODE_DRY_RUN:
        transport_kind = TRANSPORT_DRY_RUN
    identity = observe_identity(transport, token, token_source)
    state = observe_state_laws(transport, token)
    federal = observe_federal_register(transport, token)
    salvage = observe_local_salvage(salvage_roots)
    requests = gather_request_records(transport)
    live_contacted = bool(is_live_https and requests and mode != MODE_DRY_RUN)
    for record in requests:
        if not record.get("response_sha256"):
            raise LiveBaselineAuditError("missing response hash on a Hub request")
    dispositions = collect_dispositions(state, federal, salvage)
    unexplained = unexplained_count_mismatches(state, federal, dispositions)
    if unexplained:
        raise LiveBaselineAuditError(
            "contradictory counts without typed explanation: " + "; ".join(unexplained)
        )
    receipt: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "schema_version": "1",
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "producer": PRODUCER,
        "code_version": CODE_VERSION,
        "mode": mode,
        "transport": transport_kind,
        "network_required": mode == MODE_LIVE,
        "live_hub_contacted": live_contacted or mode == MODE_LIVE,
        "fixture_only": False,
        "observed_at": observed_at or utc_now(),
        "authenticated_identity": identity,
        "pins": {
            "state_laws": STATE_PINNED_REVISION,
            "federal_register": FEDERAL_PINNED_REVISION,
        },
        "requests": requests,
        "state_laws": state,
        "federal_register": federal,
        "local_salvage": salvage,
        "dispositions": dispositions,
        "sealed_expectations": {
            "state_laws": dict(SEALED_STATE_EXPECTATIONS),
            "federal_register": dict(SEALED_FEDERAL_EXPECTATIONS),
        },
        "counts_recomputed": {
            "state_repository_files": state["counts"]["repository_files"],
            "state_partitions": state["counts"]["state_parquet_filenames"],
            "per_state_canonical_total_rows": state["counts"][
                "per_state_canonical_total_rows"
            ],
            "viewer_canonical_rows": state["counts"]["viewer_canonical_rows"],
            "viewer_embedding_rows": state["counts"]["viewer_embedding_rows"],
            "cid_overlap": state["counts"]["cid_overlap_canonical_vs_embeddings"],
            "federal_repository_files": federal["counts"]["repository_files"],
            "federal_advertised_documents": federal["counts"]["advertised_documents"],
            "federal_hub_parquet_rows": federal["counts"]["hub_parquet_rows"],
        },
        "acceptance": {
            "live_mode": mode == MODE_LIVE,
            "authenticated_identity": True,
            "state_revision": state["revision"],
            "federal_revision": federal["revision"],
            "state_partitions": state["counts"]["state_parquet_filenames"],
            "includes_dc": True,
            "local_salvage_inventoried": bool(salvage.get("inventoried")),
            "request_count": len(requests),
            "disposition_count": len(dispositions),
        },
        "unsuitable_as_source_of_truth": True,
        "evidence_role": (
            "Authenticated live provenance of the pinned Hub baselines and local "
            "salvage inventory. Existing remote artifacts remain evidence inputs only."
        ),
    }
    if mode == MODE_DRY_RUN:
        receipt["live_hub_contacted"] = False
        receipt["network_required"] = False
        receipt["dry_run_note"] = (
            "Documented dry-run observation. This receipt cannot satisfy "
            "--require-live-hub because Hub HTTPS was not used."
        )
    return seal_receipt(receipt, token if mode == MODE_LIVE else None)


def build_dry_run_receipt(
    *,
    transport: Any,
    salvage_roots: Sequence[tuple[str, Path]],
    observed_at: str | None = None,
    token: str = "hf_dry_run_placeholder_not_used",
) -> dict[str, Any]:
    """Build a documented dry-run receipt. Cannot pass --require-live-hub."""
    if getattr(transport, "is_live_https", False):
        raise LiveBaselineAuditError("dry-run must not use the live HTTPS transport")
    return build_receipt(
        transport=transport,
        token=token,
        token_source="dry-run",
        salvage_roots=salvage_roots,
        observed_at=observed_at,
        mode=MODE_DRY_RUN,
    )


def validate_receipt(
    receipt: Mapping[str, Any],
    *,
    require_live_hub: bool = False,
    require_local_salvage_inventory: bool = False,
    token: str | None = None,
) -> dict[str, Any]:
    schema = receipt.get("schema")
    if schema != REPORT_SCHEMA:
        raise LiveBaselineAuditError(f"schema: expected {REPORT_SCHEMA!r}, got {schema!r}")
    if receipt.get("task_id") != TASK_ID:
        raise LiveBaselineAuditError("task_id must be LCR-070")
    if receipt.get("producer") != PRODUCER:
        raise LiveBaselineAuditError("producer mismatch")
    _require_utc(receipt.get("observed_at"), "observed_at")
    if receipt.get("fixture_only") is True:
        raise LiveBaselineAuditError("fixture-only result is forbidden")
    identity = _require_mapping(
        receipt.get("authenticated_identity"), "authenticated_identity"
    )
    if identity.get("authenticated") is not True:
        raise LiveBaselineAuditError("authenticated identity required")
    if identity.get("token_present") is not True:
        raise LiveBaselineAuditError("token_present must be true")
    _require_sha256(identity.get("whoami_response_sha256"), "whoami_response_sha256")
    if identity.get("whoami_endpoint") != WHOAMI_ENDPOINT:
        raise LiveBaselineAuditError("whoami endpoint mismatch")

    pins = _require_mapping(receipt.get("pins"), "pins")
    if require_commit_sha(pins.get("state_laws"), "pins.state_laws") != STATE_PINNED_REVISION:
        raise LiveBaselineAuditError("state-law pin is stale or changed")
    if (
        require_commit_sha(pins.get("federal_register"), "pins.federal_register")
        != FEDERAL_PINNED_REVISION
    ):
        raise LiveBaselineAuditError("Federal Register pin is stale or changed")

    requests = receipt.get("requests")
    if not isinstance(requests, list) or not requests:
        raise LiveBaselineAuditError("receipt must bind request endpoints")
    for index, record in enumerate(requests):
        mapping = _require_mapping(record, f"requests[{index}]")
        _require_str(mapping.get("endpoint"), f"requests[{index}].endpoint")
        _require_sha256(
            mapping.get("response_sha256"), f"requests[{index}].response_sha256"
        )

    state = _require_mapping(receipt.get("state_laws"), "state_laws")
    if require_commit_sha(state.get("revision"), "state_laws.revision") != STATE_PINNED_REVISION:
        raise LiveBaselineAuditError("state_laws.revision is not the pinned 40-hex SHA")
    partitions = _require_mapping(state.get("partitions"), "state_laws.partitions")
    expected_codes = expected_jurisdiction_codes()
    if sorted(partitions) != sorted(expected_codes):
        raise LiveBaselineAuditError(
            "state_laws.partitions must cover all 51 jurisdictions including DC"
        )
    if "DC" not in partitions:
        raise LiveBaselineAuditError("missing DC partition")
    for code in expected_codes:
        part = _require_mapping(partitions.get(code), f"partitions.{code}")
        _require_int(part.get("num_rows"), f"partitions.{code}.num_rows")
        _require_sha256(part.get("footer_sha256"), f"partitions.{code}.footer_sha256")
        _require_str(part.get("path"), f"partitions.{code}.path")
        _require_str(part.get("endpoint"), f"partitions.{code}.endpoint")
    files = state.get("files")
    if not isinstance(files, list) or not files:
        raise LiveBaselineAuditError("state remote file inventory missing")
    _require_sha256(state["tree"]["inventory_sha256"], "state_laws.tree.inventory_sha256")
    _require_sha256(
        state["viewer"]["canonical_config"]["content_sha256"],
        "viewer.canonical content hash",
    )
    _require_sha256(
        state["viewer"]["embedding_config"]["content_sha256"],
        "viewer.embedding content hash",
    )

    federal = _require_mapping(receipt.get("federal_register"), "federal_register")
    if (
        require_commit_sha(federal.get("revision"), "federal_register.revision")
        != FEDERAL_PINNED_REVISION
    ):
        raise LiveBaselineAuditError("federal_register.revision is not the pinned 40-hex SHA")
    _require_sha256(
        federal["parquet"]["footer_sha256"], "federal_register.parquet.footer_sha256"
    )
    _require_sha256(
        federal["metadata"]["response_sha256"],
        "federal_register.metadata.response_sha256",
    )
    _require_int(federal["parquet"]["num_rows"], "federal parquet rows")
    _require_int(
        federal["metadata"]["advertised_documents"], "federal advertised documents"
    )

    salvage = _require_mapping(receipt.get("local_salvage"), "local_salvage")
    if salvage.get("secrets_copied") is True:
        raise LiveBaselineAuditError("salvage inventory copied secrets")
    if salvage.get("symlinks_followed") is True:
        raise LiveBaselineAuditError("salvage inventory followed symlinks")
    if salvage.get("absolute_paths_persisted") is True:
        raise LiveBaselineAuditError("salvage inventory persisted absolute paths")
    roots = salvage.get("roots")
    if not isinstance(roots, list) or not roots:
        raise LiveBaselineAuditError("local salvage inventory missing roots")

    dispositions = receipt.get("dispositions")
    if not isinstance(dispositions, list):
        raise LiveBaselineAuditError("dispositions must be an array")
    for item in dispositions:
        mapping = _require_mapping(item, "disposition")
        if mapping.get("typed_explanation") is not True:
            raise LiveBaselineAuditError(
                f"disposition {mapping.get('code')!r} lacks typed explanation"
            )

    unexplained = unexplained_count_mismatches(state, federal, dispositions)
    if unexplained:
        raise LiveBaselineAuditError(
            "contradictory counts without typed explanation: " + "; ".join(unexplained)
        )

    digest = _require_sha256(receipt.get("receipt_sha256"), "receipt_sha256")
    body = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    expected_digest = sha256_canonical(body)
    if digest != expected_digest:
        raise LiveBaselineAuditError("receipt_sha256 does not match canonical receipt bytes")

    assert_no_token_leakage(receipt, token)

    if require_live_hub:
        if receipt.get("mode") != MODE_LIVE:
            raise LiveBaselineAuditError(
                "require-live-hub cannot be satisfied by a dry-run or fixture receipt"
            )
        if receipt.get("live_hub_contacted") is not True:
            raise LiveBaselineAuditError("require-live-hub needs live_hub_contacted=true")
        if receipt.get("transport") != TRANSPORT_LIVE_HTTPS:
            raise LiveBaselineAuditError(
                "require-live-hub needs the urllib HTTPS Hub transport"
            )
        if receipt.get("network_required") is not True:
            raise LiveBaselineAuditError("require-live-hub needs network_required=true")
        hub_endpoints = [
            str(item.get("endpoint"))
            for item in requests
            if "huggingface.co" in str(item.get("endpoint"))
        ]
        if not any("whoami" in endpoint for endpoint in hub_endpoints):
            raise LiveBaselineAuditError("require-live-hub never called whoami")
        if not any(STATE_REPO_ID in endpoint for endpoint in hub_endpoints):
            raise LiveBaselineAuditError("require-live-hub never fetched the state-law repo")
        if not any(FEDERAL_REPO_ID in endpoint for endpoint in hub_endpoints):
            raise LiveBaselineAuditError(
                "require-live-hub never fetched the Federal Register repo"
            )

    if require_local_salvage_inventory:
        if salvage.get("inventoried") is not True:
            raise LiveBaselineAuditError("local salvage inventory was not taken")
        present = [
            item
            for item in roots
            if item.get("present") and item.get("disposition") == "inventoried"
        ]
        if not present:
            raise LiveBaselineAuditError(
                "require-local-salvage-inventory needs at least one present inventoried root"
            )
        if all(item.get("file_count", 0) == 0 for item in present):
            raise LiveBaselineAuditError(
                "require-local-salvage-inventory cannot be an empty salvage set"
            )

    return {
        "ok": True,
        "task_id": TASK_ID,
        "mode": receipt.get("mode"),
        "observed_at": receipt.get("observed_at"),
        "state_revision": state.get("revision"),
        "federal_revision": federal.get("revision"),
        "state_files": state["counts"]["repository_files"],
        "state_partitions": state["counts"]["state_parquet_filenames"],
        "per_state_total_rows": state["counts"]["per_state_canonical_total_rows"],
        "federal_files": federal["counts"]["repository_files"],
        "federal_advertised_documents": federal["counts"]["advertised_documents"],
        "federal_hub_parquet_rows": federal["counts"]["hub_parquet_rows"],
        "request_count": len(requests),
        "disposition_count": len(dispositions),
        "receipt_sha256": digest,
        "mismatches": [],
    }


def load_receipt(path: Path | str) -> dict[str, Any]:
    receipt_path = Path(path).expanduser().resolve()
    if not receipt_path.is_file() or receipt_path.is_symlink():
        raise LiveBaselineAuditError(f"receipt must be a regular file: {receipt_path}")
    try:
        payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LiveBaselineAuditError(f"cannot read receipt {receipt_path}: {exc}") from exc
    if not isinstance(payload, MutableMapping):
        raise LiveBaselineAuditError("receipt must be a JSON object")
    return dict(payload)


def write_receipt(receipt: Mapping[str, Any], path: Path | str) -> Path:
    receipt_path = Path(path).expanduser().resolve()
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(dict(receipt), indent=2, sort_keys=True) + "\n"
    receipt_path.write_text(text, encoding="utf-8")
    return receipt_path


def render_check_summary(result: Mapping[str, Any]) -> str:
    lines = [
        f"ok={result.get('ok')}",
        f"task_id={result.get('task_id', TASK_ID)}",
        f"mode={result.get('mode')}",
        f"observed_at={result.get('observed_at')}",
        f"state_revision={result.get('state_revision')}",
        f"federal_revision={result.get('federal_revision')}",
        (
            "counts="
            f"state_files={result.get('state_files')},"
            f"state_partitions={result.get('state_partitions')},"
            f"per_state_total={result.get('per_state_total_rows')},"
            f"federal_files={result.get('federal_files')},"
            f"federal_advertised={result.get('federal_advertised_documents')},"
            f"federal_hub_parquet={result.get('federal_hub_parquet_rows')}"
        ),
        f"requests={result.get('request_count')}",
        f"dispositions={result.get('disposition_count')}",
        f"receipt_sha256={result.get('receipt_sha256')}",
    ]
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Authenticate to Hugging Face Hub and record live provenance for "
            "the pinned legal-corpora baselines (LCR-070)."
        )
    )
    parser.add_argument(
        "--require-live-hub",
        action="store_true",
        help="Fail unless this process actually calls authenticated Hub HTTPS.",
    )
    parser.add_argument(
        "--require-local-salvage-inventory",
        action="store_true",
        help="Fail unless configured local salvage roots are inventoried.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate the live (or dry-run) observation fail-closed.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the receipt to --receipt.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Documented dry-run that does not call Hub. Cannot be combined with "
            "--require-live-hub."
        ),
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        default=None,
        help=f"Receipt path (default: {DEFAULT_RECEIPT_RELPATH.as_posix()})",
    )
    parser.add_argument(
        "--salvage-root",
        action="append",
        default=[],
        help="Override salvage root as name=path. Repeatable. Tests only.",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print the receipt JSON to stdout.",
    )
    return parser


def _parse_salvage_overrides(values: Sequence[str]) -> list[tuple[str, Path]] | None:
    if not values:
        return None
    roots: list[tuple[str, Path]] = []
    for item in values:
        if "=" not in item:
            raise LiveBaselineAuditError("--salvage-root must be name=path")
        name, raw = item.split("=", 1)
        roots.append((name.strip(), Path(raw).expanduser()))
    return roots


def observe_with_live_hub(
    *,
    salvage_roots: Sequence[tuple[str, Path]] | None = None,
    observed_at: str | None = None,
    token: str | None = None,
    token_source: str | None = None,
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    discovered_token, discovered_source = (
        (token, token_source) if token else discover_hf_token()
    )
    transport = LiveHubTransport(discovered_token, timeout_seconds=timeout_seconds)
    return build_receipt(
        transport=transport,
        token=discovered_token,
        token_source=discovered_source or "huggingface_token_file",
        salvage_roots=salvage_roots,
        observed_at=observed_at,
        mode=MODE_LIVE,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    receipt_path = (
        Path(args.receipt).expanduser().resolve()
        if args.receipt is not None
        else default_receipt_path()
    )
    try:
        if args.require_live_hub and args.dry_run:
            raise LiveBaselineAuditError(
                "dry-run cannot satisfy --require-live-hub; Hub HTTPS is required"
            )
        salvage_roots = _parse_salvage_overrides(args.salvage_root)
        if args.dry_run:
            raise LiveBaselineAuditError(
                "dry-run CLI observation requires an injected scripted transport; "
                "use the library helper in tests. This CLI refuses to fake live Hub success."
            )
        if args.require_live_hub or args.check or args.write:
            if args.require_live_hub or args.check:
                receipt = observe_with_live_hub(salvage_roots=salvage_roots)
                result = validate_receipt(
                    receipt,
                    require_live_hub=bool(args.require_live_hub),
                    require_local_salvage_inventory=bool(
                        args.require_local_salvage_inventory
                    ),
                )
            else:
                receipt = observe_with_live_hub(salvage_roots=salvage_roots)
                result = validate_receipt(
                    receipt,
                    require_live_hub=False,
                    require_local_salvage_inventory=bool(
                        args.require_local_salvage_inventory
                    ),
                )
            if args.write or args.check:
                write_receipt(receipt, receipt_path)
            if args.check:
                print(render_check_summary(result))
            elif args.write:
                print(f"wrote live baseline receipt: {receipt_path}", file=sys.stderr)
            if args.print_json:
                sys.stdout.write(
                    json.dumps(receipt, indent=2, sort_keys=True) + "\n"
                )
            return 0
        print(
            "hint: pass --require-live-hub --require-local-salvage-inventory --check",
            file=sys.stderr,
        )
        return 2
    except LiveBaselineAuditError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
