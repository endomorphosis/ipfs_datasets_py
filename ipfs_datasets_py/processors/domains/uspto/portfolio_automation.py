"""Operator portfolio automation helpers (public ODP + authorized private import).

This module automates **review prep**, not legal submission:

* Discover candidate public applications via ODP search
* Maintain a local portfolio seed
* Batch-refresh public status through production runtime bootstrap
* Build Patent Center export manifests from a local download folder
* Drive authorized ``import-private`` into a tenant store
* Aggregate per-matter prior-art / compliance-audit / IDS status (content-free)

It never accepts Patent Center passwords, MFA secrets, session cookies as
CLI args, or signs/pays/files. Browser automation lives in the attended ops
script and only produces local export packages for this import path.
Matter status dashboards never emit secrets or PDF/document bodies.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Final, Iterable, Mapping, Sequence

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    AuthorityRelation,
    DisclosureClassification,
)
from ipfs_datasets_py.processors.domains.uspto.providers.credential_resolver import (
    CredentialResolver,
)
from ipfs_datasets_py.processors.domains.uspto.providers.patent_center_export import (
    PATENT_CENTER_EXPORT_SCHEMA_VERSION,
    ExportManifest,
    ExportManifestEntry,
    ImportAuthorization,
    PatentCenterExportProvider,
)
from ipfs_datasets_py.processors.domains.uspto.private_store import (
    PrivateArtifactStore,
    TenantKeyMaterial,
    generate_tenant_key,
)
from ipfs_datasets_py.processors.domains.uspto.runtime import bootstrap_production

PORTFOLIO_AUTOMATION_SCHEMA: Final = "patlaw-portfolio-automation-v1"
PORTFOLIO_SEED_SCHEMA: Final = "patlaw-portfolio-seed-v1"
MATTER_STATUS_SCHEMA: Final = "patlaw-portfolio-matter-status-v1"
UNIFIED_APPLICATION_REVIEW_SCHEMA: Final = "paar.UnifiedApplicationReview@1"
MATTER_STATUS_DISCLAIMER: Final = (
    "Review-only matter status. Not a readiness certification, patentability "
    "opinion, or filing authorization. Never auto-files an IDS; Sign/Pay/Submit "
    "remain human-only. Output is content-free metadata (counts, ids, statuses) "
    "and never includes secrets, credentials, or PDF/document bodies."
)
DEFAULT_TENANT_ID: Final = "operator-default"
DEFAULT_INVENTOR_QUERY_FIELD: Final = (
    "applicationMetaData.inventorBag.inventorNameText"
)

# Closed vocabularies for UnifiedApplicationReview dashboard fields (PAAR-120).
_REVIEW_RISK_TIERS: Final = frozenset({"unknown", "low", "medium", "high"})
_REVIEW_CONFORMANCE_STATUSES: Final = frozenset(
    {"satisfied", "unsatisfied", "unknown", "human_only"}
)
_REVIEW_DISPOSITIONS: Final = frozenset(
    {"ready", "review_required", "not_ready"}
)

# Keys that must never appear in matter-status operator output.
_MATTER_STATUS_SECRET_KEY_FRAGMENTS: Final = frozenset(
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
        "pdf_body",
        "private_key",
        "totp",
    }
)
_MATTER_STATUS_MAX_STR: Final = 240
_MATTER_STATUS_MAX_ACTIONS: Final = 40
_MATTER_STATUS_MAX_GAPS: Final = 40
_MATTER_STATUS_MAX_HUMAN_ITEMS: Final = 40

# Attended browser export is an operator capability. Unattended scrape remains
# forbidden (see private_boundary_policy.json and patent_center_export).
ALLOWED_OPERATOR_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {
        "discover_public_odp",
        "sync_public_status",
        "sync_public_documents",
        "build_export_manifest_from_folder",
        "import_user_authorized_export",
        "attended_browser_export_with_human_login",
        "watch_download_folder",
    }
)

FORBIDDEN_OPERATOR_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {
        "store_credentials_or_cookies",
        "bypass_mfa",
        "automate_mfa",
        "network_login_with_password",
        "unattended_patent_center_scrape",
        "apply_signature",
        "pay_fee",
        "perform_final_submission",
        "read_browser_password_manager",
    }
)

_APP_NO_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9/]{2,31}\Z")


class PortfolioAutomationError(RuntimeError):
    """Fail-closed operator automation error (no secret material)."""

    def __init__(self, message: str, *, code: str = "portfolio_automation_error") -> None:
        super().__init__(message)
        self.code = code

    def audit_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


class ForbiddenOperatorCapabilityError(PortfolioAutomationError):
    def __init__(self, capability: str) -> None:
        super().__init__(
            f"forbidden operator capability: {capability}",
            code="forbidden_operator_capability",
        )
        self.capability = capability


def assert_operator_capability(capability: str) -> None:
    key = str(capability or "").strip()
    if key in FORBIDDEN_OPERATOR_CAPABILITIES:
        raise ForbiddenOperatorCapabilityError(key)
    if key not in ALLOWED_OPERATOR_CAPABILITIES:
        raise PortfolioAutomationError(
            f"unknown operator capability: {key}",
            code="unknown_operator_capability",
        )


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def default_state_root() -> Path:
    xdg = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "state"
    return base / "ipfs_datasets_py" / "patent_portfolio" / DEFAULT_TENANT_ID


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize_application_number_token(value: str) -> str:
    text = str(value or "").strip().replace(",", "").replace(" ", "")
    if not text:
        raise PortfolioAutomationError(
            "application number is required", code="missing_application_number"
        )
    # Keep slash form when present; ODP often accepts compact form.
    return text


# ---------------------------------------------------------------------------
# Portfolio seed
# ---------------------------------------------------------------------------


@dataclass
class PortfolioMatter:
    application_number: str
    title: str = ""
    applicant: str = ""
    filing_date: str = ""
    status_odp_search: str = ""
    ownership: str = "candidate_unconfirmed"
    match_basis: str = ""
    labels: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "application_number": self.application_number,
            "title": self.title,
            "applicant": self.applicant,
            "filing_date": self.filing_date,
            "status_odp_search": self.status_odp_search,
            "ownership": self.ownership,
            "match_basis": self.match_basis,
            "labels": dict(self.labels),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PortfolioMatter":
        return cls(
            application_number=str(value.get("application_number") or "").strip(),
            title=str(value.get("title") or ""),
            applicant=str(value.get("applicant") or ""),
            filing_date=str(value.get("filing_date") or ""),
            status_odp_search=str(
                value.get("status_odp_search") or value.get("status") or ""
            ),
            ownership=str(value.get("ownership") or "candidate_unconfirmed"),
            match_basis=str(value.get("match_basis") or ""),
            labels={str(k): str(v) for k, v in dict(value.get("labels") or {}).items()},
        )


@dataclass
class PortfolioSeed:
    tenant_id: str
    matters: list[PortfolioMatter]
    credential_ref: str = "env:USPTO_ODP_API_KEY"
    created_at_utc: str = ""
    discovery: dict[str, Any] = field(default_factory=dict)
    schema: str = PORTFOLIO_SEED_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "tenant_id": self.tenant_id,
            "created_at_utc": self.created_at_utc or utc_now_iso(),
            "credential_ref": self.credential_ref,
            "discovery": dict(self.discovery),
            "matters": [m.to_dict() for m in self.matters],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PortfolioSeed":
        matters_raw = value.get("matters") or []
        if not isinstance(matters_raw, list):
            raise PortfolioAutomationError("matters must be a list", code="invalid_seed")
        return cls(
            schema=str(value.get("schema") or PORTFOLIO_SEED_SCHEMA),
            tenant_id=str(value.get("tenant_id") or DEFAULT_TENANT_ID),
            created_at_utc=str(value.get("created_at_utc") or ""),
            credential_ref=str(value.get("credential_ref") or "env:USPTO_ODP_API_KEY"),
            discovery=dict(value.get("discovery") or {}),
            matters=[PortfolioMatter.from_dict(m) for m in matters_raw if isinstance(m, Mapping)],
        )


def load_portfolio_seed(path: Path) -> PortfolioSeed:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise PortfolioAutomationError("seed must be a JSON object", code="invalid_seed")
    return PortfolioSeed.from_dict(data)


def save_portfolio_seed(seed: PortfolioSeed, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(seed.to_dict(), indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def merge_matters(
    existing: Sequence[PortfolioMatter],
    incoming: Sequence[PortfolioMatter],
) -> list[PortfolioMatter]:
    by_app: dict[str, PortfolioMatter] = {}
    for matter in existing:
        key = normalize_application_number_token(matter.application_number)
        by_app[key] = matter
    for matter in incoming:
        key = normalize_application_number_token(matter.application_number)
        prior = by_app.get(key)
        if prior is None:
            by_app[key] = matter
            continue
        # Prefer confirmed ownership and non-empty descriptive fields.
        ownership = prior.ownership
        if prior.ownership.startswith("candidate") and not matter.ownership.startswith(
            "candidate"
        ):
            ownership = matter.ownership
        by_app[key] = PortfolioMatter(
            application_number=prior.application_number or matter.application_number,
            title=prior.title or matter.title,
            applicant=prior.applicant or matter.applicant,
            filing_date=prior.filing_date or matter.filing_date,
            status_odp_search=matter.status_odp_search or prior.status_odp_search,
            ownership=ownership,
            match_basis=prior.match_basis or matter.match_basis,
            labels={**prior.labels, **matter.labels},
        )
    return list(by_app.values())


# ---------------------------------------------------------------------------
# Public ODP discovery / status
# ---------------------------------------------------------------------------


def inventorf_phrase_query(inventor_name: str) -> str:
    name = str(inventor_name or "").strip()
    if not name:
        raise PortfolioAutomationError("inventor_name is required", code="missing_inventor")
    # Escape embedded quotes in the phrase.
    safe = name.replace('"', "")
    return f'{DEFAULT_INVENTOR_QUERY_FIELD}:"{safe}"'


def discover_public_by_inventor(
    inventor_name: str,
    *,
    api_key: str | None = None,
    limit: int = 50,
    sleep_seconds: float = 0.0,
    http_post: Callable[[str, dict[str, str], bytes], tuple[int, dict[str, Any]]] | None = None,
) -> list[PortfolioMatter]:
    """Search ODP for public applications matching an inventor display name.

    Results are **candidates** (same-name collisions are common). Ownership is
    never asserted.
    """
    assert_operator_capability("discover_public_odp")
    key = api_key if api_key is not None else os.environ.get("USPTO_ODP_API_KEY", "")
    if not key:
        raise PortfolioAutomationError(
            "USPTO_ODP_API_KEY is not set", code="missing_odp_key"
        )
    query = inventorf_phrase_query(inventor_name)
    limit = max(1, min(int(limit), 100))
    payload = {
        "q": query,
        "pagination": {"offset": 0, "limit": limit},
        "fields": ["applicationNumberText", "applicationMetaData"],
        "sort": [{"field": "applicationMetaData.filingDate", "order": "desc"}],
    }
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "X-API-KEY": key,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "patent-legal-intelligence-portfolio-automation/1.0",
    }
    if http_post is None:
        status_code, response = _default_http_post(
            "https://api.uspto.gov/api/v1/patent/applications/search",
            headers,
            body,
        )
    else:
        status_code, response = http_post(
            "https://api.uspto.gov/api/v1/patent/applications/search",
            headers,
            body,
        )
    if status_code == 404:
        return []
    if status_code != 200:
        raise PortfolioAutomationError(
            f"ODP search failed with HTTP {status_code}",
            code="odp_search_failed",
        )
    bag = response.get("patentFileWrapperDataBag") or []
    if not isinstance(bag, list):
        return []
    needle = inventor_name.strip().lower()
    matters: list[PortfolioMatter] = []
    for item in bag:
        if not isinstance(item, Mapping):
            continue
        meta = item.get("applicationMetaData") or {}
        if not isinstance(meta, Mapping):
            meta = {}
        invs = meta.get("inventorBag") or []
        inv_names = [
            str(i.get("inventorNameText") or "")
            for i in invs
            if isinstance(i, Mapping)
        ]
        # Prefer exact phrase membership (case-insensitive).
        if needle and not any(needle == n.strip().lower() for n in inv_names):
            # Allow "Benjamin J. Barber" style partial when query was exact phrase miss.
            if not any(needle in n.strip().lower() for n in inv_names):
                continue
        apps = meta.get("applicantBag") or []
        app_names = [
            str(a.get("applicantNameText") or "")
            for a in apps
            if isinstance(a, Mapping)
        ]
        app_no = str(item.get("applicationNumberText") or meta.get("applicationNumberText") or "")
        if not app_no:
            continue
        matters.append(
            PortfolioMatter(
                application_number=app_no,
                title=str(meta.get("inventionTitle") or ""),
                applicant="; ".join(app_names[:3]),
                filing_date=str(meta.get("filingDate") or ""),
                status_odp_search=str(
                    meta.get("applicationStatusDescriptionText")
                    or meta.get("applicationStatusCode")
                    or ""
                ),
                ownership="candidate_unconfirmed",
                match_basis=f'inventorNameText search: "{inventor_name}"',
            )
        )
    if sleep_seconds > 0:
        time.sleep(sleep_seconds)
    return matters


def _default_http_post(
    url: str, headers: dict[str, str], body: bytes
) -> tuple[int, dict[str, Any]]:
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            return int(resp.status), json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            parsed = json.loads(raw.decode("utf-8", "replace") or "{}")
        except json.JSONDecodeError:
            parsed = {"error": raw[:200].decode("utf-8", "replace")}
        return int(exc.code), parsed


def _status_entry_from_payload(
    matter: PortfolioMatter, payload: Mapping[str, Any]
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "application_number": matter.application_number,
        "title": matter.title,
        "ownership": matter.ownership,
        "applicant": matter.applicant,
        "filing_date": matter.filing_date,
        "ok": True,
        "provider_kind": payload.get("provider_kind"),
        "provider_status_code": payload.get("provider_status_code"),
        "outcome": payload.get("outcome"),
    }
    freshness = payload.get("freshness") or {}
    if isinstance(freshness, Mapping):
        entry["freshness_class"] = freshness.get("freshness_class")
    snap = payload.get("snapshot") or {}
    raw: Mapping[str, Any] = {}
    status_blob: dict[str, Any] = {}
    if isinstance(snap, Mapping):
        raw_candidate = snap.get("raw_application_meta") or {}
        if isinstance(raw_candidate, Mapping):
            raw = raw_candidate
        for key in ("status", "normalized_status", "application_status"):
            nested = snap.get(key)
            if isinstance(nested, Mapping):
                status_blob = dict(nested)
                break
        for key in (
            "status_code",
            "status_text",
            "entity_status",
            "lifecycle_phase",
            "is_patented",
            "is_pending",
            "is_abandoned",
        ):
            if key in snap and key not in status_blob:
                status_blob[key] = snap[key]
    entry["status_code"] = status_blob.get("status_code") or raw.get(
        "applicationStatusCode"
    )
    entry["status_text"] = status_blob.get("status_text") or raw.get(
        "applicationStatusDescriptionText"
    )
    entry["entity_status"] = status_blob.get("entity_status")
    entry["patent_number"] = raw.get("patentNumber")
    return entry


def sync_public_documents_batch(
    seed: PortfolioSeed,
    *,
    client: Any,
    documents_root: Path,
    sleep_seconds: float = 2.0,
    force_download: bool = False,
    confirmed_only: bool = True,
    document_codes: str | Sequence[str] | None = None,
) -> dict[str, Any]:
    """Sync public ODP document inventory/bytes for seed matters.

    Uses :class:`DocumentSyncProcessor` with a durable admitted-document store
    under *documents_root*. By default only matters with non-candidate
    ownership are synced (reduces same-name noise and ODP load).
    """
    assert_operator_capability("sync_public_documents")
    from ipfs_datasets_py.processors.domains.uspto.document_sync_processor import (
        AdmittedDocumentStore,
        CheckpointStore,
        DocumentSyncProcessor,
    )

    documents_root = Path(documents_root)
    documents_root.mkdir(parents=True, exist_ok=True)
    store = AdmittedDocumentStore(root=documents_root / "admitted")
    checkpoints = CheckpointStore(root=documents_root / "checkpoints")
    quarantine = documents_root / "quarantine"
    quarantine.mkdir(parents=True, exist_ok=True)

    matters = list(seed.matters)
    if confirmed_only:
        matters = [
            m
            for m in matters
            if not str(m.ownership).startswith("candidate")
        ]

    results: list[dict[str, Any]] = []
    with DocumentSyncProcessor(
        client=client,
        store=store,
        checkpoints=checkpoints,
        quarantine_root=quarantine,
    ) as processor:
        for index, matter in enumerate(matters):
            if index and sleep_seconds > 0:
                time.sleep(sleep_seconds)
            app = matter.application_number
            entry: dict[str, Any] = {
                "application_number": app,
                "ownership": matter.ownership,
                "title": matter.title,
            }
            try:
                doc_result = processor.sync_application(
                    app,
                    document_codes=document_codes,
                    force_download=force_download,
                )
                payload = doc_result.to_dict()
                entry["ok"] = bool(doc_result.ok)
                entry["inventory_count"] = payload.get("inventory_count")
                entry["admitted_count"] = payload.get("admitted_count")
                entry["deduplicated_count"] = payload.get("deduplicated_count")
                entry["versioned_count"] = payload.get("versioned_count")
                entry["freshness_gap_count"] = payload.get("freshness_gap_count")
                entry["unavailable_count"] = payload.get("unavailable_count")
                entry["partial_rejected_count"] = payload.get(
                    "partial_rejected_count"
                )
                entry["metadata_error"] = payload.get("metadata_error")
                entry["inventory_receipt_id"] = payload.get("inventory_receipt_id")
            except Exception as exc:  # noqa: BLE001
                entry["ok"] = False
                entry["error_type"] = type(exc).__name__
                entry["error"] = str(exc)[:400]
            results.append(entry)

    return {
        "schema": "patlaw-public-document-sync-v1",
        "tenant_id": seed.tenant_id,
        "generated_at_utc": utc_now_iso(),
        "documents_root": str(documents_root),
        "confirmed_only": confirmed_only,
        "matter_count": len(matters),
        "success_count": sum(1 for r in results if r.get("ok")),
        "failure_count": sum(1 for r in results if not r.get("ok")),
        "results": results,
    }


def sync_public_status_batch(
    seed: PortfolioSeed,
    *,
    store_root: Path,
    force_refresh: bool = True,
    sleep_seconds: float = 2.0,
    credential_ref: str | None = None,
    with_documents: bool = False,
    documents_root: Path | None = None,
    force_document_download: bool = False,
    documents_confirmed_only: bool = True,
    document_codes: str | Sequence[str] | None = None,
) -> dict[str, Any]:
    """Refresh public ODP status (and optionally document inventory/bytes)."""
    assert_operator_capability("sync_public_status")
    ref = credential_ref or seed.credential_ref or "env:USPTO_ODP_API_KEY"
    store_root = Path(store_root)
    store_root.mkdir(parents=True, exist_ok=True)
    runtime = bootstrap_production(
        credential_ref=ref,
        store_root=store_root,
        tenant_id=seed.tenant_id,
        credential_resolver=CredentialResolver(),
    )
    reviews: list[dict[str, Any]] = []
    for index, matter in enumerate(seed.matters):
        if index and sleep_seconds > 0:
            time.sleep(sleep_seconds)
        app = matter.application_number
        try:
            result = runtime.status_processor.sync(
                app,
                matter_id=f"matter:{app}",
                force_refresh=force_refresh,
            )
            payload = result.to_dict() if hasattr(result, "to_dict") else {}
            entry = _status_entry_from_payload(matter, payload)
        except Exception as exc:  # noqa: BLE001 — operator batch continues
            entry = {
                "application_number": app,
                "title": matter.title,
                "ownership": matter.ownership,
                "applicant": matter.applicant,
                "filing_date": matter.filing_date,
                "ok": False,
                "error_type": type(exc).__name__,
                "error": str(exc)[:400],
            }
        reviews.append(entry)

    documents_report: dict[str, Any] | None = None
    if with_documents:
        doc_root = Path(documents_root) if documents_root else store_root.parent / "public_docs"
        documents_report = sync_public_documents_batch(
            seed,
            client=runtime.client,
            documents_root=doc_root,
            sleep_seconds=sleep_seconds,
            force_download=force_document_download,
            confirmed_only=documents_confirmed_only,
            document_codes=document_codes,
        )

    report = {
        "schema": "patlaw-public-status-review-v1",
        "tenant_id": seed.tenant_id,
        "generated_at_utc": utc_now_iso(),
        "credential_ref": ref,
        "candidate_count": len(seed.matters),
        "success_count": sum(1 for r in reviews if r.get("ok")),
        "failure_count": sum(1 for r in reviews if not r.get("ok")),
        "reviews_compact": reviews,
        "documents": documents_report,
        "next_steps": [
            "Confirm candidate ownership (same-name inventors exist).",
            "Document sync defaults to confirmed ownership only; use drop/keep-only first.",
            "For unpublished matters use attended-export or import-folder.",
            "Never store Patent Center passwords in the seed or review files.",
        ],
    }
    return report


# ---------------------------------------------------------------------------
# Local export package / import-private
# ---------------------------------------------------------------------------


_MEDIA_BY_SUFFIX: Final[Mapping[str, str]] = MappingProxyType(
    {
        ".pdf": "application/pdf",
        ".docx": (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        ".doc": "application/msword",
        ".txt": "text/plain",
        ".html": "text/html",
        ".htm": "text/html",
        ".xml": "application/xml",
        ".json": "application/json",
        ".zip": "application/zip",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
    }
)


def guess_media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in _MEDIA_BY_SUFFIX:
        return _MEDIA_BY_SUFFIX[suffix]
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def guess_entry_role(path: Path) -> str:
    name = path.name.lower()
    if "acknowledg" in name or name.startswith("ear") or "receipt" in name and "pay" not in name:
        return "acknowledgement"
    if "payment" in name or "fee" in name:
        return "payment_receipt"
    if name.endswith(".docx") or "specification" in name or "spec" in name:
        return "original_submission"
    if name.endswith(".pdf") and ("oa" in name or "office" in name or "action" in name):
        return "office_action"
    if name.endswith(".pdf"):
        return "document"
    return "export_file"


def build_export_manifest_from_folder(
    folder: Path,
    *,
    application_number: str,
    matter_id: str | None = None,
    classification: str | DisclosureClassification = (
        DisclosureClassification.CONFIDENTIAL_APPLICATION
    ),
    export_id: str | None = None,
) -> ExportManifest:
    """Build an :class:`ExportManifest` from files under *folder* (recursive)."""
    assert_operator_capability("build_export_manifest_from_folder")
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise PortfolioAutomationError(
            f"export folder does not exist: {root}", code="missing_export_folder"
        )
    app = normalize_application_number_token(application_number)
    mid = matter_id or f"matter:{app}"
    eid = export_id or f"export-{uuid.uuid4().hex[:16]}"
    classification_value = (
        classification
        if isinstance(classification, DisclosureClassification)
        else DisclosureClassification(str(classification))
    )

    entries: list[ExportManifestEntry] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name in {
            "export_manifest.json",
            "authorization.json",
            ".DS_Store",
        }:
            continue
        if path.name.startswith("."):
            continue
        rel = path.relative_to(root).as_posix()
        # ExportManifest relative paths must not use characters outside the allowlist.
        if not re.fullmatch(r"[A-Za-z0-9._\-/ ]+", rel):
            # Copy-safe: skip illegal names rather than fail the whole batch.
            continue
        entries.append(
            ExportManifestEntry(
                relative_path=rel,
                classification=classification_value,
                media_type=guess_media_type(path),
                authority_relation=AuthorityRelation.AUTHORITATIVE_ORIGINAL,
                expected_sha256=sha256_file(path),
                labels={"role": guess_entry_role(path), "source": "local_folder"},
            )
        )
    if not entries:
        raise PortfolioAutomationError(
            f"no importable files under {root}", code="empty_export_folder"
        )
    return ExportManifest(
        schema_version=PATENT_CENTER_EXPORT_SCHEMA_VERSION,
        export_id=eid,
        matter_id=mid,
        application_number=app,
        entries=tuple(entries),
        source="user_authorized_patent_center_export",
    )


def build_import_authorization(
    *,
    tenant_id: str,
    import_root: Path | str,
    authorizing_user: str,
    scope: str = "import_authorized_local_export",
    notes: Sequence[str] = (),
    authorization_id: str | None = None,
) -> ImportAuthorization:
    return ImportAuthorization(
        schema_version=PATENT_CENTER_EXPORT_SCHEMA_VERSION,
        authorization_id=authorization_id or f"authz-{uuid.uuid4().hex[:16]}",
        authorizing_user=str(authorizing_user).strip() or "operator:local",
        tenant_id=str(tenant_id).strip(),
        granted_utc=utc_now_iso(),
        import_root=str(Path(import_root).expanduser().resolve()),
        scope=scope,
        notes=tuple(notes)
        or (
            "Operator-authorized local export import; no Patent Center password stored.",
        ),
    )


def write_export_package_sidecar(
    folder: Path,
    *,
    application_number: str,
    tenant_id: str,
    authorizing_user: str,
    classification: str = DisclosureClassification.CONFIDENTIAL_APPLICATION.value,
) -> dict[str, Path]:
    """Write export_manifest.json + authorization.json into *folder*."""
    root = Path(folder).expanduser().resolve()
    manifest = build_export_manifest_from_folder(
        root,
        application_number=application_number,
        classification=classification,
    )
    auth = build_import_authorization(
        tenant_id=tenant_id,
        import_root=root,
        authorizing_user=authorizing_user,
        notes=(
            "Generated by portfolio_automation.write_export_package_sidecar",
            "Human authorized local import of Patent Center downloads.",
        ),
    )
    manifest_path = root / "export_manifest.json"
    auth_path = root / "authorization.json"
    manifest_path.write_text(json.dumps(manifest.to_dict(), indent=2) + "\n")
    auth_path.write_text(json.dumps(auth.to_dict(), indent=2) + "\n")
    return {"manifest": manifest_path, "authorization": auth_path, "import_root": root}


def import_export_folder(
    folder: Path,
    *,
    tenant_id: str,
    application_number: str,
    authorizing_user: str,
    store_root: Path,
    tenant_key_path: Path | None = None,
    classification: str = DisclosureClassification.CONFIDENTIAL_APPLICATION.value,
    fail_fast: bool = False,
) -> dict[str, Any]:
    """Build sidecars if needed and import into the private artifact store."""
    assert_operator_capability("import_user_authorized_export")
    root = Path(folder).expanduser().resolve()
    paths = write_export_package_sidecar(
        root,
        application_number=application_number,
        tenant_id=tenant_id,
        authorizing_user=authorizing_user,
        classification=classification,
    )
    manifest = ExportManifest.from_dict(
        json.loads(paths["manifest"].read_text(encoding="utf-8"))
    )
    authorization = ImportAuthorization.from_dict(
        json.loads(paths["authorization"].read_text(encoding="utf-8"))
    )
    store_root = Path(store_root).expanduser().resolve()
    store_root.mkdir(parents=True, exist_ok=True)
    if tenant_key_path and Path(tenant_key_path).is_file():
        key = TenantKeyMaterial(
            tenant_id=tenant_id, key_bytes=Path(tenant_key_path).read_bytes()
        )
    else:
        key_file = store_root / f"{tenant_id}.tenant.key"
        if key_file.is_file():
            key = TenantKeyMaterial(tenant_id=tenant_id, key_bytes=key_file.read_bytes())
        else:
            key = generate_tenant_key(tenant_id)
            key_file.write_bytes(key.key_bytes)
            try:
                os.chmod(key_file, 0o600)
            except OSError:
                pass
    store = PrivateArtifactStore(store_root, key)
    provider = PatentCenterExportProvider(store)
    result = provider.import_export(
        import_root=root,
        authorization=authorization,
        manifest=manifest,
        fail_fast=fail_fast,
    )
    payload = result.to_dict() if hasattr(result, "to_dict") else {"result": str(result)}
    return {
        "schema": PORTFOLIO_AUTOMATION_SCHEMA,
        "tenant_id": tenant_id,
        "application_number": application_number,
        "import_root": str(root),
        "store_root": str(store_root),
        "manifest_path": str(paths["manifest"]),
        "authorization_path": str(paths["authorization"]),
        "import_result": payload,
    }


def confirm_ownership(
    seed: PortfolioSeed,
    application_numbers: Iterable[str],
    *,
    ownership: str = "confirmed_operator",
) -> PortfolioSeed:
    wanted = {
        normalize_application_number_token(a) for a in application_numbers if str(a).strip()
    }
    updated: list[PortfolioMatter] = []
    for matter in seed.matters:
        key = normalize_application_number_token(matter.application_number)
        if key in wanted:
            updated.append(
                PortfolioMatter(
                    application_number=matter.application_number,
                    title=matter.title,
                    applicant=matter.applicant,
                    filing_date=matter.filing_date,
                    status_odp_search=matter.status_odp_search,
                    ownership=ownership,
                    match_basis=matter.match_basis,
                    labels=dict(matter.labels),
                )
            )
        else:
            updated.append(matter)
    seed.matters = updated
    return seed


def drop_matters(
    seed: PortfolioSeed,
    application_numbers: Iterable[str],
) -> tuple[PortfolioSeed, list[str]]:
    """Remove application numbers from the seed. Returns (seed, dropped_ids)."""
    drop = {
        normalize_application_number_token(a) for a in application_numbers if str(a).strip()
    }
    kept: list[PortfolioMatter] = []
    dropped: list[str] = []
    for matter in seed.matters:
        key = normalize_application_number_token(matter.application_number)
        if key in drop:
            dropped.append(matter.application_number)
        else:
            kept.append(matter)
    seed.matters = kept
    return seed, dropped


def summarize_public_documents(documents_root: Path) -> dict[str, Any]:
    """Summarize durable public document checkpoints (content-free metadata)."""
    root = Path(documents_root)
    checkpoints_dir = root / "checkpoints"
    admitted_dir = root / "admitted"
    apps: list[dict[str, Any]] = []
    if checkpoints_dir.is_dir():
        for path in sorted(checkpoints_dir.glob("doc-sync-*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, Mapping):
                continue
            entries = payload.get("entries") or {}
            if not isinstance(entries, Mapping):
                entries = {}
            outcomes: dict[str, int] = {}
            sample_files: list[str] = []
            for entry in entries.values():
                if not isinstance(entry, Mapping):
                    continue
                outcome = str(entry.get("last_outcome") or "unknown")
                outcomes[outcome] = outcomes.get(outcome, 0) + 1
                marker = entry.get("marker") or {}
                if isinstance(marker, Mapping):
                    url = str(marker.get("download_url") or "")
                    if url:
                        sample_files.append(url.rsplit("/", 1)[-1][:120])
            apps.append(
                {
                    "application_number": payload.get("application_number"),
                    "document_count": len(entries),
                    "outcomes": outcomes,
                    "inventory_receipt_id": payload.get("inventory_receipt_id"),
                    "inventory_retrieved_utc": payload.get("inventory_retrieved_utc"),
                    "sample_filenames": sample_files[:12],
                    "checkpoint_path": str(path),
                }
            )
    admitted_bins = 0
    admitted_bytes = 0
    if admitted_dir.is_dir():
        for bin_path in admitted_dir.glob("*.bin"):
            admitted_bins += 1
            try:
                admitted_bytes += bin_path.stat().st_size
            except OSError:
                pass
    return {
        "schema": "patlaw-public-docs-summary-v1",
        "documents_root": str(root),
        "application_count": len(apps),
        "admitted_bin_count": admitted_bins,
        "admitted_bytes": admitted_bytes,
        "applications": apps,
        "generated_at_utc": utc_now_iso(),
    }


def _matter_status_is_secret_key(key: str) -> bool:
    lowered = str(key or "").strip().lower().replace("-", "_")
    if not lowered:
        return False
    if lowered in _MATTER_STATUS_SECRET_KEY_FRAGMENTS:
        return True
    return any(frag in lowered for frag in _MATTER_STATUS_SECRET_KEY_FRAGMENTS)


def _matter_status_safe_str(value: Any, *, max_len: int = _MATTER_STATUS_MAX_STR) -> str:
    """Bound free-form text; strip credential-like substrings when available."""
    if value is None:
        return ""
    text = str(value)
    try:
        from ipfs_datasets_py.processors.domains.uspto.providers.base import (
            sanitize_secret_text,
        )

        text = sanitize_secret_text(text)
    except Exception:  # noqa: BLE001 — fail closed to truncated plain text
        pass
    text = text.replace("\x00", "")
    # Drop obvious PDF / binary markers rather than echoing bodies.
    if text.startswith("%PDF") or "stream\n" in text[:64]:
        return "<redacted:binary-or-pdf>"
    if len(text) > max_len:
        return text[: max(0, max_len - 3)] + "..."
    return text


def _matter_status_redact(value: Any, *, depth: int = 0) -> Any:
    """Recursively drop secret-bearing keys and bound strings (no PDF bodies)."""
    if depth > 8:
        return "<redacted:max-depth>"
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for raw_key, raw_val in value.items():
            key = str(raw_key)
            if _matter_status_is_secret_key(key):
                continue
            out[key] = _matter_status_redact(raw_val, depth=depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [_matter_status_redact(v, depth=depth + 1) for v in value[:80]]
    if isinstance(value, (bytes, bytearray)):
        return f"<redacted:bytes:{len(value)}>"
    if isinstance(value, str):
        return _matter_status_safe_str(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _matter_status_safe_str(value)


def _matter_status_read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    return dict(payload)


def _matter_status_mtime(path: Path) -> float:
    try:
        return float(path.stat().st_mtime)
    except OSError:
        return -1.0


def _discover_matter_app_ids(
    state: Path,
    *,
    seed_apps: Sequence[str] | None = None,
    application_numbers: Sequence[str] | None = None,
    include_orphans: bool = True,
) -> list[str]:
    """Ordered unique application numbers for the matter dashboard."""
    ordered: list[str] = []
    seen: set[str] = set()

    def _add(raw: str) -> None:
        app = normalize_application_number_token(raw)
        if not app or app in seen:
            return
        seen.add(app)
        ordered.append(app)

    if application_numbers:
        for raw in application_numbers:
            _add(str(raw))
        return ordered

    for raw in seed_apps or ():
        _add(str(raw))

    if include_orphans:
        for sub in (
            "prior_art",
            "compliance_audits",
            "ids_queues",
            "reviews",
            "unified_reviews",
        ):
            root = state / sub
            if not root.is_dir():
                continue
            for child in sorted(root.iterdir()):
                if child.is_dir():
                    _add(child.name)
                elif child.is_file() and child.suffix.lower() == ".json":
                    # Flat review pointer files named <app>.json
                    _add(child.stem)
    return ordered


def _summarize_latest_prior_art_run(
    state: Path, application_number: str
) -> dict[str, Any] | None:
    """Content-free summary of the newest prior-art run for one matter."""
    app = normalize_application_number_token(application_number)
    app_dir = state / "prior_art" / app
    if not app_dir.is_dir():
        return None

    best: tuple[float, Path, dict[str, Any]] | None = None
    for run_dir in app_dir.iterdir():
        if not run_dir.is_dir():
            continue
        man_path = run_dir / "run_manifest.json"
        payload = _matter_status_read_json(man_path) if man_path.is_file() else None
        if payload is None:
            payload = {"run_id": run_dir.name, "action": "unknown"}
        stamp = str(
            payload.get("created_at_utc")
            or payload.get("generated_at_utc")
            or ""
        )
        mtime = _matter_status_mtime(man_path if man_path.is_file() else run_dir)
        # Prefer lexicographic UTC stamps when present; else mtime.
        sort_key = float(
            "".join(c for c in stamp if c.isdigit())[:14] or 0
        ) or mtime
        if best is None or sort_key >= best[0]:
            best = (sort_key, run_dir, payload)

    if best is None:
        return None

    _, run_dir, payload = best
    paths = payload.get("paths") if isinstance(payload.get("paths"), Mapping) else {}
    # Presence flags only — never expand path contents or PDF names beyond count.
    artifact_flags = {
        "has_plan": (run_dir / "prior_art_plan.json").is_file()
        or bool(paths.get("plan") or paths.get("prior_art_plan")),
        "has_journal": (run_dir / "search_journal.json").is_file()
        or bool(paths.get("journal") or paths.get("search_journal")),
        "has_report": (run_dir / "prior_art_report.json").is_file()
        or bool(paths.get("report") or paths.get("prior_art_report")),
        "has_ids_queue": (run_dir / "ids_review_queue.json").is_file(),
        "has_pps_verification": (run_dir / "pps_verification.json").is_file()
        or (run_dir / "pps_verification_checklist.json").is_file(),
        "has_human_ack": (run_dir / "human_coverage_acknowledgment.json").is_file()
        or bool(paths.get("human_ack")),
    }
    backends = payload.get("backends")
    backends_out: dict[str, Any] = {}
    if isinstance(backends, Mapping):
        for k, v in backends.items():
            if isinstance(v, bool) or v is None:
                backends_out[str(k)] = v
            else:
                backends_out[str(k)] = _matter_status_safe_str(v, max_len=64)

    return {
        "present": True,
        "run_id": _matter_status_safe_str(
            payload.get("run_id") or run_dir.name, max_len=128
        ),
        "run_dir": str(run_dir),
        "action": _matter_status_safe_str(payload.get("action") or "", max_len=64),
        "created_at_utc": _matter_status_safe_str(
            payload.get("created_at_utc") or payload.get("generated_at_utc") or "",
            max_len=64,
        ),
        "hit_count": int(payload.get("hit_count") or 0),
        "gap_count": int(payload.get("gap_count") or 0),
        "plan_id": _matter_status_safe_str(payload.get("plan_id") or "", max_len=128)
        or None,
        "journal_id": _matter_status_safe_str(
            payload.get("journal_id") or "", max_len=128
        )
        or None,
        "backends": backends_out,
        "artifacts": artifact_flags,
    }


def _summarize_latest_compliance_audit(
    state: Path, application_number: str
) -> dict[str, Any] | None:
    """Content-free summary of the newest compliance audit for one matter."""
    app = normalize_application_number_token(application_number)
    app_dir = state / "compliance_audits" / app
    if not app_dir.is_dir():
        return None

    best: tuple[float, Path, dict[str, Any]] | None = None
    for audit_dir in app_dir.iterdir():
        if not audit_dir.is_dir():
            continue
        man_path = audit_dir / "submission_compliance_audit.json"
        if not man_path.is_file():
            continue
        payload = _matter_status_read_json(man_path)
        if payload is None:
            continue
        stamp = str(payload.get("generated_at_utc") or "")
        mtime = _matter_status_mtime(man_path)
        sort_key = float(
            "".join(c for c in stamp if c.isdigit())[:14] or 0
        ) or mtime
        if best is None or sort_key >= best[0]:
            best = (sort_key, audit_dir, payload)

    if best is None:
        return None

    _, audit_dir, payload = best
    delta = payload.get("delta") if isinstance(payload.get("delta"), Mapping) else {}
    prior = payload.get("prior_art") if isinstance(payload.get("prior_art"), Mapping) else {}
    filing = (
        payload.get("filing_rules")
        if isinstance(payload.get("filing_rules"), Mapping)
        else {}
    )
    ids_q = payload.get("ids_queue") if isinstance(payload.get("ids_queue"), Mapping) else {}
    action_plan = payload.get("action_plan")
    if not isinstance(action_plan, list):
        plan_file = _matter_status_read_json(audit_dir / "action_plan.json") or {}
        raw_actions = plan_file.get("actions") if isinstance(plan_file, Mapping) else None
        action_plan = raw_actions if isinstance(raw_actions, list) else []

    residual_actions: list[dict[str, Any]] = []
    for action in action_plan[:_MATTER_STATUS_MAX_ACTIONS]:
        if not isinstance(action, Mapping):
            continue
        residual_actions.append(
            {
                "priority": int(action.get("priority") or 99),
                "code": _matter_status_safe_str(action.get("code") or "", max_len=96),
                "title": _matter_status_safe_str(
                    action.get("title") or "", max_len=160
                ),
                # CLI template only — already content-free; still sanitize.
                "command": _matter_status_safe_str(
                    action.get("command") or "", max_len=220
                )
                or None,
            }
        )

    open_gap_codes: list[str] = []
    for code in prior.get("blocking_codes") or []:
        open_gap_codes.append(f"prior_art:blocking:{_matter_status_safe_str(code, max_len=64)}")
    for code in prior.get("warning_codes") or []:
        open_gap_codes.append(f"prior_art:warning:{_matter_status_safe_str(code, max_len=64)}")
    for gap in filing.get("evidence_gaps") or []:
        if not isinstance(gap, Mapping):
            continue
        status = str(gap.get("status") or "")
        if status not in {"missing", "human_only", "optional_missing"}:
            continue
        kind = _matter_status_safe_str(gap.get("evidence_kind") or "unknown", max_len=48)
        rule = _matter_status_safe_str(gap.get("rule_id") or "", max_len=64)
        open_gap_codes.append(f"filing:{kind}:{status}:{rule}".rstrip(":"))
    open_gap_codes = open_gap_codes[:_MATTER_STATUS_MAX_GAPS]

    action_plan_count = int(
        payload.get("action_plan_count")
        or len(action_plan)
        or 0
    )

    return {
        "present": True,
        "audit_id": _matter_status_safe_str(
            payload.get("audit_id") or audit_dir.name, max_len=128
        ),
        "audit_dir": str(audit_dir),
        "overall_status": _matter_status_safe_str(
            payload.get("overall_status") or "", max_len=64
        ),
        "revision_id": _matter_status_safe_str(
            payload.get("revision_id") or "", max_len=128
        )
        or None,
        "generated_at_utc": _matter_status_safe_str(
            payload.get("generated_at_utc") or "", max_len=64
        ),
        "delta_from": _matter_status_safe_str(payload.get("delta_from") or "", max_len=128)
        or None,
        "closed_gap_count": int(delta.get("closed_gap_count") or 0)
        if delta
        else None,
        "opened_gap_count": int(delta.get("opened_gap_count") or 0)
        if delta
        else None,
        "status_transition": (
            {
                "from": _matter_status_safe_str(
                    (delta.get("status_transition") or {}).get("from") or "",
                    max_len=64,
                )
                or None,
                "to": _matter_status_safe_str(
                    (delta.get("status_transition") or {}).get("to") or "",
                    max_len=64,
                )
                or None,
                "changed": bool(
                    (delta.get("status_transition") or {}).get("changed")
                ),
            }
            if isinstance(delta.get("status_transition"), Mapping)
            else None
        ),
        "prior_art_status": _matter_status_safe_str(
            prior.get("status") or "", max_len=64
        )
        or None,
        "ids_candidates_on_audit": int(ids_q.get("candidate_count") or 0)
        if ids_q
        else None,
        "action_plan_count": action_plan_count,
        "action_residuals": {
            "residual_count": len(residual_actions),
            "actions": residual_actions,
            "open_gap_count": len(open_gap_codes),
            "open_gap_codes": open_gap_codes,
        },
    }


def _review_stamp_sort_key(payload: Mapping[str, Any], path: Path) -> float:
    """Prefer lexicographic UTC stamps; fall back to mtime."""
    stamp = str(
        payload.get("generated_at_utc")
        or payload.get("created_at_utc")
        or ""
    )
    digits = "".join(c for c in stamp if c.isdigit())[:14]
    if digits:
        try:
            return float(digits)
        except ValueError:
            pass
    return _matter_status_mtime(path)


def _normalize_risk_tier(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    if text in _REVIEW_RISK_TIERS:
        return text
    return "unknown" if not text else _matter_status_safe_str(text, max_len=32)


def _normalize_conformance_status(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    if text in _REVIEW_CONFORMANCE_STATUSES:
        return text
    return "unknown" if not text else _matter_status_safe_str(text, max_len=32)


def _normalize_disposition(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    if text in _REVIEW_DISPOSITIONS:
        return text
    return "review_required" if not text else _matter_status_safe_str(text, max_len=32)


def _pointer_ref(
    ref: Mapping[str, Any] | None,
    *,
    risk_key: str | None = None,
    status_key: str | None = None,
) -> dict[str, Any] | None:
    """Content-free pointer fields only (ids, digests, paths, status enums)."""
    if not isinstance(ref, Mapping):
        return None
    out: dict[str, Any] = {}
    for key in ("report_id", "path", "content_digest", "schema"):
        val = ref.get(key)
        if val is None or val == "":
            continue
        out[key] = _matter_status_safe_str(val, max_len=220)
    if risk_key and ref.get(risk_key) is not None:
        out[risk_key] = _normalize_risk_tier(ref.get(risk_key))
    if status_key and ref.get(status_key) is not None:
        out[status_key] = _normalize_conformance_status(ref.get(status_key))
    return out or None


def _extract_open_human_items(
    payload: Mapping[str, Any],
    *,
    risk_tier: str,
    conformance_status: str,
    disposition: str,
) -> list[dict[str, Any]]:
    """Build content-free open human items from UnifiedApplicationReview fields.

    Emits ids/kinds/statuses only — never claim quotes, hit bodies, or PDF paths
    contents. Pointer path fields are allowed when present on residual rows.
    """
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(
        item_id: str,
        *,
        kind: str,
        status: str = "open",
        source: str = "unified_review",
        path: str | None = None,
    ) -> None:
        iid = _matter_status_safe_str(item_id, max_len=128) or kind
        key = f"{kind}:{iid}"
        if key in seen:
            return
        seen.add(key)
        row: dict[str, Any] = {
            "item_id": iid,
            "kind": _matter_status_safe_str(kind, max_len=64),
            "status": _matter_status_safe_str(status, max_len=48),
            "source": _matter_status_safe_str(source, max_len=64),
        }
        if path:
            # Path pointer only — never read file contents.
            row["path"] = _matter_status_safe_str(path, max_len=220)
        items.append(row)

    # Coverage gaps (named corpora / adapters — no body text).
    gaps = payload.get("coverage_gaps")
    if isinstance(gaps, list):
        for gap in gaps:
            if not isinstance(gap, Mapping):
                continue
            gap_kind = str(
                gap.get("kind")
                or gap.get("gap_kind")
                or gap.get("corpus")
                or "coverage_gap"
            )
            gap_status = str(gap.get("status") or "open")
            gap_id = str(
                gap.get("gap_id")
                or gap.get("id")
                or f"gap:{gap_kind}:{gap_status}"
            )
            _add(
                gap_id,
                kind="coverage_gap",
                status=gap_status,
                source="coverage_gaps",
                path=str(gap.get("path") or "") or None,
            )

    # Diligence residuals (pack / check pointers).
    residuals = payload.get("diligence_residuals")
    if isinstance(residuals, list):
        for residual in residuals:
            if not isinstance(residual, Mapping):
                continue
            rid = str(
                residual.get("residual_id")
                or residual.get("id")
                or residual.get("check_id")
                or residual.get("kind")
                or "residual"
            )
            rkind = str(residual.get("kind") or "diligence_residual")
            rstatus = str(
                residual.get("status")
                or residual.get("state")
                or "open"
            )
            _add(
                rid,
                kind=rkind if rkind != "coverage_gap" else "diligence_coverage_gap",
                status=rstatus,
                source="diligence_residuals",
                path=str(
                    residual.get("path")
                    or residual.get("pack_path")
                    or residual.get("pointer")
                    or ""
                )
                or None,
            )

    # Explicit open_human_items array if present on the review payload.
    explicit = payload.get("open_human_items")
    if isinstance(explicit, list):
        for row in explicit:
            if not isinstance(row, Mapping):
                continue
            _add(
                str(row.get("item_id") or row.get("id") or row.get("kind") or "item"),
                kind=str(row.get("kind") or "human_item"),
                status=str(row.get("status") or "open"),
                source="open_human_items",
                path=str(row.get("path") or "") or None,
            )

    # Reasons list (short codes only).
    reasons = payload.get("reasons")
    if isinstance(reasons, list):
        for reason in reasons:
            if isinstance(reason, Mapping):
                code = str(reason.get("code") or reason.get("reason") or "")
            else:
                code = str(reason or "")
            code = code.strip()
            if not code:
                continue
            # Skip free-form paragraphs; keep short codes.
            if len(code) > 96 or " " in code and len(code) > 48:
                code = code.split()[0][:64]
            _add(code, kind="reason", status="open", source="reasons")

    # Medium/high conflict risk without human dispositions remains open.
    dispositions = payload.get("dispositions")
    has_dispositions = isinstance(dispositions, list) and len(dispositions) > 0
    conflict_ref = (
        payload.get("conflict_risk_ref")
        if isinstance(payload.get("conflict_risk_ref"), Mapping)
        else {}
    )
    if risk_tier in {"medium", "high"} and not has_dispositions:
        _add(
            f"conflict_risk:{risk_tier}:needs_disposition",
            kind="conflict_risk_disposition",
            status="needs_human",
            source="conflict_risk_ref",
            path=str(conflict_ref.get("path") or "") or None,
        )

    if conformance_status in {"unsatisfied", "unknown", "human_only"}:
        conf_ref = (
            payload.get("conformance_ref")
            if isinstance(payload.get("conformance_ref"), Mapping)
            else {}
        )
        _add(
            f"conformance:{conformance_status}",
            kind="conformance",
            status=conformance_status,
            source="conformance_ref",
            path=str(conf_ref.get("path") or "") or None,
        )

    if disposition in {"review_required", "not_ready"}:
        _add(
            f"disposition:{disposition}",
            kind="disposition",
            status=disposition,
            source="disposition",
        )

    return items[:_MATTER_STATUS_MAX_HUMAN_ITEMS]


def _iter_unified_review_candidates(state: Path, app: str) -> list[Path]:
    """Locate unified_application_review.json files for one application."""
    candidates: list[Path] = []
    seen: set[str] = set()

    def _add(path: Path) -> None:
        try:
            key = str(path.resolve())
        except OSError:
            key = str(path)
        if key in seen:
            return
        if path.is_file():
            seen.add(key)
            candidates.append(path)

    # Canonical persist layout from PAAR-090:
    #   state/compliance_audits/<app>/review_<stamp>/unified_application_review.json
    app_audit = state / "compliance_audits" / app
    if app_audit.is_dir():
        for path in app_audit.rglob("unified_application_review.json"):
            _add(path)
        # Compact summary may stand alone when full report is absent.
        for path in app_audit.rglob("summary.json"):
            parent = path.parent
            if (parent / "unified_application_review.json").is_file():
                continue
            # Only treat summary.json under review_* dirs as review status.
            if parent.name.startswith("review_") or "review" in parent.name.lower():
                _add(path)

    reviews_root = state / "reviews" / app
    if reviews_root.is_dir():
        for path in reviews_root.rglob("unified_application_review.json"):
            _add(path)
        for path in reviews_root.rglob("summary.json"):
            if (path.parent / "unified_application_review.json").is_file():
                continue
            _add(path)

    # Flat per-app pointer files (operator-friendly).
    for flat in (
        state / "reviews" / f"{app}.json",
        state / "unified_reviews" / f"{app}.json",
        state / "unified_reviews" / app / "unified_application_review.json",
    ):
        _add(flat)

    return candidates


def _summarize_latest_unified_review(
    state: Path, application_number: str
) -> dict[str, Any] | None:
    """Content-free summary of the newest UnifiedApplicationReview for one matter.

    Dashboard fields (PAAR-120 / PAAR-G130):
    * pointer path to the review artifact (never PDF/document bodies)
    * risk_tier (conflict matter_risk)
    * conformance_status
    * open_human_items (ids/kinds only)
    """
    app = normalize_application_number_token(application_number)
    if not app:
        return None

    best: tuple[float, Path, dict[str, Any]] | None = None
    for path in _iter_unified_review_candidates(state, app):
        payload = _matter_status_read_json(path)
        if payload is None:
            continue
        # Accept full UnifiedApplicationReview or compact summary with same fields.
        schema = str(payload.get("schema") or "")
        has_review_shape = any(
            key in payload
            for key in (
                "review_id",
                "disposition",
                "conflict_risk_ref",
                "conformance_ref",
                "risk_tier",
                "matter_risk",
            )
        )
        if not has_review_shape and "UnifiedApplicationReview" not in schema:
            # summary.json from other tools — skip unless it looks like a review.
            if path.name != "summary.json":
                continue
            if not (
                payload.get("disposition") is not None
                or payload.get("exit_code_hint") is not None
            ):
                continue
        sort_key = _review_stamp_sort_key(payload, path)
        if best is None or sort_key >= best[0]:
            best = (sort_key, path, payload)

    if best is None:
        return None

    _, review_path, payload = best
    review_dir = review_path.parent

    conflict_ref_raw = (
        payload.get("conflict_risk_ref")
        if isinstance(payload.get("conflict_risk_ref"), Mapping)
        else None
    )
    conformance_ref_raw = (
        payload.get("conformance_ref")
        if isinstance(payload.get("conformance_ref"), Mapping)
        else None
    )

    # risk_tier: prefer explicit field, then conflict_risk_ref.matter_risk, then matter_risk
    risk_tier = _normalize_risk_tier(
        payload.get("risk_tier")
        or (conflict_ref_raw or {}).get("matter_risk")
        or payload.get("matter_risk")
        or "unknown"
    )
    conformance_status = _normalize_conformance_status(
        payload.get("conformance_status")
        or (conformance_ref_raw or {}).get("overall_status")
        or payload.get("overall_status")
        or "unknown"
    )
    disposition = _normalize_disposition(payload.get("disposition") or "review_required")

    try:
        exit_hint = int(payload.get("exit_code_hint"))
    except (TypeError, ValueError):
        exit_hint = {"ready": 0, "review_required": 1, "not_ready": 2}.get(
            disposition, 1
        )

    open_items = _extract_open_human_items(
        payload,
        risk_tier=risk_tier,
        conformance_status=conformance_status,
        disposition=disposition,
    )

    # Companion files are pointers only.
    full_path = review_dir / "unified_application_review.json"
    summary_path = review_dir / "summary.json"
    pointer_path = str(review_path)
    if full_path.is_file():
        pointer_path = str(full_path)

    coverage_gaps = payload.get("coverage_gaps")
    coverage_gap_count = (
        len(coverage_gaps) if isinstance(coverage_gaps, list) else 0
    )
    diligence = payload.get("diligence_residuals")
    diligence_count = len(diligence) if isinstance(diligence, list) else 0

    conflict_ref = _pointer_ref(conflict_ref_raw, risk_key="matter_risk")
    conformance_ref = _pointer_ref(conformance_ref_raw, status_key="overall_status")

    return {
        "present": True,
        "schema": _matter_status_safe_str(
            payload.get("schema") or UNIFIED_APPLICATION_REVIEW_SCHEMA, max_len=96
        ),
        "review_id": _matter_status_safe_str(
            payload.get("review_id") or review_dir.name, max_len=128
        ),
        # UnifiedApplicationReview pointer — path only, never body.
        "path": pointer_path,
        "review_dir": str(review_dir),
        "summary_path": str(summary_path) if summary_path.is_file() else None,
        "content_digest": _matter_status_safe_str(
            payload.get("content_digest") or "", max_len=128
        )
        or None,
        "generated_at_utc": _matter_status_safe_str(
            payload.get("generated_at_utc") or payload.get("created_at_utc") or "",
            max_len=64,
        ),
        "disposition": disposition,
        "exit_code_hint": exit_hint,
        "risk_tier": risk_tier,
        "conformance_status": conformance_status,
        "conflict_risk_ref": conflict_ref,
        "conformance_ref": conformance_ref,
        "open_human_items": open_items,
        "open_human_item_count": len(open_items),
        "coverage_gap_count": coverage_gap_count,
        "diligence_residual_count": diligence_count,
        "auto_file_blocked": bool(payload.get("auto_file_blocked", True)),
        "review_only": True,
    }


def _empty_unified_review() -> dict[str, Any]:
    return {
        "present": False,
        "review_id": None,
        "path": None,
        "disposition": None,
        "risk_tier": None,
        "conformance_status": None,
        "open_human_items": [],
        "open_human_item_count": 0,
        "auto_file_blocked": True,
    }


def _summarize_ids_counts(
    state: Path,
    application_number: str,
    *,
    prior_art_run_dir: str | None = None,
) -> dict[str, Any]:
    """IDS queue counts for a matter (no citation text / PDF bodies)."""
    app = normalize_application_number_token(application_number)
    candidates: list[Path] = []

    if prior_art_run_dir:
        p = Path(prior_art_run_dir) / "ids_review_queue.json"
        if p.is_file():
            candidates.append(p)

    prior_root = state / "prior_art" / app
    if prior_root.is_dir():
        candidates.extend(prior_root.rglob("ids_review_queue.json"))

    ids_root = state / "ids_queues" / app
    if ids_root.is_dir():
        candidates.extend(ids_root.glob("*.json"))

    # Newest mtime wins.
    newest: Path | None = None
    newest_mtime = -1.0
    seen_paths: set[str] = set()
    for path in candidates:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen_paths:
            continue
        seen_paths.add(key)
        if not path.is_file():
            continue
        m = _matter_status_mtime(path)
        if m > newest_mtime:
            newest_mtime = m
            newest = path

    empty = {
        "present": False,
        "queue_id": None,
        "queue_path": None,
        "candidate_count": 0,
        "ids_ready_count": 0,
        "by_state": {},
        "auto_file_blocked": True,
        "claims_exhaustive_search": False,
    }
    if newest is None:
        return empty

    payload = _matter_status_read_json(newest)
    if payload is None:
        return {**empty, "present": True, "queue_path": str(newest), "error": "unreadable"}

    rows = payload.get("candidates") if isinstance(payload.get("candidates"), list) else []
    by_state: dict[str, int] = {}
    ready = 0
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        state_name = str(
            row.get("state")
            or ("ids_ready" if row.get("is_ids_ready") else "candidate")
        )
        # Prefer enum value strings.
        if hasattr(state_name, "value"):
            state_name = str(getattr(state_name, "value"))
        state_name = _matter_status_safe_str(state_name, max_len=48) or "unknown"
        by_state[state_name] = by_state.get(state_name, 0) + 1
        if row.get("is_ids_ready") or state_name in {"ids_ready", "IDS_READY"}:
            ready += 1

    return {
        "present": True,
        "queue_id": _matter_status_safe_str(payload.get("queue_id") or "", max_len=128)
        or None,
        "queue_path": str(newest),
        "candidate_count": len(rows),
        "ids_ready_count": ready,
        "by_state": by_state,
        "auto_file_blocked": bool(payload.get("auto_file_blocked", True)),
        "claims_exhaustive_search": bool(payload.get("claims_exhaustive_search", False)),
    }


def _seed_info_from_matter(
    seed_matter: PortfolioMatter | Mapping[str, Any],
) -> dict[str, Any]:
    if isinstance(seed_matter, PortfolioMatter):
        return {
            "ownership": seed_matter.ownership,
            "title": _matter_status_safe_str(seed_matter.title, max_len=100),
            "status_odp_search": _matter_status_safe_str(
                seed_matter.status_odp_search, max_len=80
            ),
            "filing_date": _matter_status_safe_str(
                seed_matter.filing_date, max_len=32
            ),
            "applicant": _matter_status_safe_str(seed_matter.applicant, max_len=100),
        }
    return {
        "ownership": _matter_status_safe_str(
            seed_matter.get("ownership") or "", max_len=64
        ),
        "title": _matter_status_safe_str(seed_matter.get("title") or "", max_len=100),
        "status_odp_search": _matter_status_safe_str(
            seed_matter.get("status_odp_search") or seed_matter.get("status") or "",
            max_len=80,
        ),
        "filing_date": _matter_status_safe_str(
            seed_matter.get("filing_date") or "", max_len=32
        ),
        "applicant": _matter_status_safe_str(
            seed_matter.get("applicant") or "", max_len=100
        ),
    }


def summarize_matter_status(
    state_root: Path | str,
    application_number: str,
    *,
    seed_matter: PortfolioMatter | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Per-matter prior-art / audit residual / IDS triage summary (content-free)."""
    state = Path(state_root)
    app = normalize_application_number_token(application_number)
    seed_info: dict[str, Any] | None = None
    if seed_matter is not None:
        seed_info = _seed_info_from_matter(seed_matter)
    else:
        # Auto-resolve seed membership when callers pass only an application number.
        seed_path = state / "portfolio_seed.json"
        if seed_path.is_file():
            try:
                seed = load_portfolio_seed(seed_path)
            except Exception:  # noqa: BLE001
                seed = None
            if seed is not None:
                for matter in seed.matters:
                    if normalize_application_number_token(matter.application_number) == app:
                        seed_info = _seed_info_from_matter(matter)
                        break

    prior = _summarize_latest_prior_art_run(state, app)
    audit = _summarize_latest_compliance_audit(state, app)
    review = _summarize_latest_unified_review(state, app)
    ids = _summarize_ids_counts(
        state,
        app,
        prior_art_run_dir=(prior or {}).get("run_dir") if prior else None,
    )

    residuals = (audit or {}).get("action_residuals") if audit else None
    if residuals is None:
        residuals = {
            "residual_count": 0,
            "actions": [],
            "open_gap_count": 0,
            "open_gap_codes": [],
        }

    review_block = review or _empty_unified_review()
    # Top-level convenience mirrors for dashboard consumers (PAAR-120).
    risk_tier = review_block.get("risk_tier") if review_block.get("present") else None
    conformance_status = (
        review_block.get("conformance_status") if review_block.get("present") else None
    )

    row = {
        "application_number": app or str(application_number).strip(),
        "in_seed": seed_info is not None,
        "seed": seed_info,
        "prior_art": prior
        or {
            "present": False,
            "run_id": None,
            "hit_count": 0,
            "gap_count": 0,
        },
        "audit": (
            {
                "present": True,
                "audit_id": audit["audit_id"],
                "overall_status": audit["overall_status"],
                "generated_at_utc": audit["generated_at_utc"],
                "revision_id": audit.get("revision_id"),
                "delta_from": audit.get("delta_from"),
                "closed_gap_count": audit.get("closed_gap_count"),
                "opened_gap_count": audit.get("opened_gap_count"),
                "status_transition": audit.get("status_transition"),
                "prior_art_status": audit.get("prior_art_status"),
                "action_plan_count": audit.get("action_plan_count"),
                "ids_candidates_on_audit": audit.get("ids_candidates_on_audit"),
            }
            if audit
            else {
                "present": False,
                "audit_id": None,
                "overall_status": None,
                "action_plan_count": 0,
            }
        ),
        # PAAR-120: latest UnifiedApplicationReview pointer + risk/conformance.
        "review": review_block,
        "unified_review": review_block,
        "risk_tier": risk_tier,
        "conformance_status": conformance_status,
        "open_human_items": list(review_block.get("open_human_items") or []),
        "action_residuals": residuals,
        "ids": ids,
        "triage_hints": _matter_status_triage_hints(
            prior=prior,
            audit=audit,
            ids=ids,
            residuals=residuals,
            review=review_block,
        ),
    }
    return _matter_status_redact(row)


def _matter_status_triage_hints(
    *,
    prior: Mapping[str, Any] | None,
    audit: Mapping[str, Any] | None,
    ids: Mapping[str, Any] | None,
    residuals: Mapping[str, Any] | None,
    review: Mapping[str, Any] | None = None,
) -> list[str]:
    """Short operator next-step hints (never secrets)."""
    hints: list[str] = []
    review_map = review or {}
    if review_map.get("present"):
        disposition = str(review_map.get("disposition") or "")
        risk = str(review_map.get("risk_tier") or "")
        conf = str(review_map.get("conformance_status") or "")
        if disposition and disposition != "ready":
            hints.append(
                f"unified review disposition is {disposition} "
                f"(risk={risk or 'unknown'}, conformance={conf or 'unknown'})"
            )
        human_n = int(review_map.get("open_human_item_count") or 0)
        if human_n:
            hints.append(f"{human_n} open human item(s) on latest review")
        if risk in {"medium", "high"}:
            hints.append(f"conflict risk tier is {risk} — human disposition required")
        if conf in {"unsatisfied", "unknown"}:
            hints.append(f"conformance status is {conf} — review package obligations")
    else:
        hints.append("run unified application review for this matter")
    if not prior or not prior.get("present"):
        hints.append("run prior-art search for this matter")
    if not audit or not audit.get("present"):
        hints.append("run compliance audit (audit-submission / revise audit)")
    else:
        status = str(audit.get("overall_status") or "")
        if status and status not in {"ready_for_human_filing", "ready"}:
            hints.append(f"audit status is {status} — review action residuals")
        residual_count = int((residuals or {}).get("residual_count") or 0)
        if residual_count:
            hints.append(f"{residual_count} open action residual(s)")
    ids_map = ids or {}
    if ids_map.get("present"):
        cand = int(ids_map.get("candidate_count") or 0)
        ready = int(ids_map.get("ids_ready_count") or 0)
        if cand and ready == 0:
            hints.append(f"{cand} IDS candidate(s) awaiting human relevance/materiality review")
        elif ready:
            hints.append(
                f"{ready} IDS-ready reference(s) — human file only (auto-file blocked)"
            )
    elif prior and prior.get("present"):
        hints.append("build IDS candidate queue from prior-art hits for human review")
    if not hints:
        hints.append("no open triage signals — re-audit after package changes")
    return hints[:8]


def build_portfolio_matter_status(
    state_root: Path | str,
    *,
    application_numbers: Sequence[str] | None = None,
    include_orphans: bool = True,
) -> dict[str, Any]:
    """Portfolio-wide per-matter status: prior-art, audit, residuals, IDS, review.

    Operator-safe: never prints secrets, credentials, API keys, or PDF/document
    bodies. Status is review-only and is not a readiness certification.

    PAAR-120 dashboard fields per matter include the latest
    UnifiedApplicationReview pointer path, risk_tier, conformance_status, and
    open_human_items (content-free; pointer paths only).
    """
    state = Path(state_root)
    seed_path = state / "portfolio_seed.json"
    seed_by_app: dict[str, PortfolioMatter] = {}
    tenant_id: str | None = None
    if seed_path.is_file():
        try:
            seed = load_portfolio_seed(seed_path)
            tenant_id = seed.tenant_id
            for matter in seed.matters:
                key = normalize_application_number_token(matter.application_number)
                if key:
                    seed_by_app[key] = matter
        except Exception:  # noqa: BLE001
            tenant_id = None

    apps = _discover_matter_app_ids(
        state,
        seed_apps=list(seed_by_app.keys()),
        application_numbers=application_numbers,
        include_orphans=include_orphans
        if not application_numbers
        else False,
    )

    matters: list[dict[str, Any]] = []
    totals: dict[str, Any] = {
        "with_prior_art": 0,
        "with_audit": 0,
        "with_ids_queue": 0,
        "with_unified_review": 0,
        "ids_ready_total": 0,
        "ids_candidate_total": 0,
        "residual_action_total": 0,
        "open_human_item_total": 0,
        "audit_status_counts": {},
        "risk_tier_counts": {},
        "conformance_status_counts": {},
        "disposition_counts": {},
    }
    for app in apps:
        row = summarize_matter_status(
            state,
            app,
            seed_matter=seed_by_app.get(app),
        )
        matters.append(row)
        if (row.get("prior_art") or {}).get("present"):
            totals["with_prior_art"] += 1
        audit = row.get("audit") or {}
        if audit.get("present"):
            totals["with_audit"] += 1
            st = str(audit.get("overall_status") or "unknown")
            counts = totals["audit_status_counts"]
            counts[st] = int(counts.get(st) or 0) + 1
        ids = row.get("ids") or {}
        if ids.get("present"):
            totals["with_ids_queue"] += 1
            totals["ids_ready_total"] += int(ids.get("ids_ready_count") or 0)
            totals["ids_candidate_total"] += int(ids.get("candidate_count") or 0)
        residuals = row.get("action_residuals") or {}
        totals["residual_action_total"] += int(residuals.get("residual_count") or 0)

        review = row.get("review") or row.get("unified_review") or {}
        if review.get("present"):
            totals["with_unified_review"] += 1
            risk = str(review.get("risk_tier") or row.get("risk_tier") or "unknown")
            conf = str(
                review.get("conformance_status")
                or row.get("conformance_status")
                or "unknown"
            )
            disp = str(review.get("disposition") or "unknown")
            risk_counts = totals["risk_tier_counts"]
            risk_counts[risk] = int(risk_counts.get(risk) or 0) + 1
            conf_counts = totals["conformance_status_counts"]
            conf_counts[conf] = int(conf_counts.get(conf) or 0) + 1
            disp_counts = totals["disposition_counts"]
            disp_counts[disp] = int(disp_counts.get(disp) or 0) + 1
            totals["open_human_item_total"] += int(
                review.get("open_human_item_count")
                or len(review.get("open_human_items") or [])
                or 0
            )

    payload = {
        "schema": MATTER_STATUS_SCHEMA,
        "ok": True,
        "generated_at_utc": utc_now_iso(),
        "state_root": str(state),
        "tenant_id": tenant_id,
        "matter_count": len(matters),
        "matters": matters,
        "totals": totals,
        "disclaimer": MATTER_STATUS_DISCLAIMER,
        "review_only": True,
        "hard_barriers": {
            "sign": "human_only",
            "pay": "human_only",
            "submit": "human_only",
            "ids_auto_file": "blocked",
        },
    }
    return _matter_status_redact(payload)


def build_portfolio_dashboard(state_root: Path) -> dict[str, Any]:
    """Aggregate seed, last review, public docs, exports, schedule, and PAAR-120 fields."""
    state = Path(state_root)
    seed_path = state / "portfolio_seed.json"
    review_path = state / "public_status_review.json"
    docs_root = state / "public_docs"
    exports_dir = state / "exports"
    inbox_dir = state / "private_inbox"
    schedule_manifest = state / "schedule" / "install_manifest.json"

    seed_payload: dict[str, Any] | None = None
    seed_apps: list[str] = []
    if seed_path.is_file():
        seed = load_portfolio_seed(seed_path)
        seed_apps = [
            normalize_application_number_token(m.application_number)
            for m in seed.matters
            if normalize_application_number_token(m.application_number)
        ]
        seed_payload = {
            "tenant_id": seed.tenant_id,
            "matter_count": len(seed.matters),
            "confirmed_count": sum(
                1
                for m in seed.matters
                if not str(m.ownership).startswith("candidate")
            ),
            "candidate_count": sum(
                1 for m in seed.matters if str(m.ownership).startswith("candidate")
            ),
            "matters": [
                {
                    "application_number": m.application_number,
                    "ownership": m.ownership,
                    "title": (m.title or "")[:100],
                    "status_odp_search": m.status_odp_search,
                    "filing_date": m.filing_date,
                    "applicant": m.applicant,
                }
                for m in seed.matters
            ],
        }

    review_summary: dict[str, Any] | None = None
    if review_path.is_file():
        try:
            review = json.loads(review_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            review = None
        if isinstance(review, Mapping):
            docs = review.get("documents") if isinstance(review.get("documents"), Mapping) else {}
            review_summary = {
                "generated_at_utc": review.get("generated_at_utc"),
                "success_count": review.get("success_count"),
                "failure_count": review.get("failure_count"),
                "documents_enabled": bool(docs),
                "documents_success_count": docs.get("success_count") if docs else None,
                "documents_failure_count": docs.get("failure_count") if docs else None,
            }

    export_dirs = []
    if exports_dir.is_dir():
        for child in sorted(exports_dir.iterdir()):
            if not child.is_dir():
                continue
            files = [
                p.name
                for p in child.rglob("*")
                if p.is_file()
                and p.name
                not in {"export_manifest.json", "authorization.json", ".DS_Store"}
            ]
            export_dirs.append(
                {
                    "name": child.name,
                    "path": str(child),
                    "file_count": len(files),
                    "sealed": (child / "export_manifest.json").is_file(),
                }
            )

    inbox_dirs = []
    if inbox_dir.is_dir():
        for child in sorted(inbox_dir.iterdir()):
            if child.is_dir():
                inbox_dirs.append(_inbox_folder_status(child))

    schedule: dict[str, Any] | None = None
    if schedule_manifest.is_file():
        try:
            schedule = json.loads(schedule_manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            schedule = {"error": "unreadable_manifest"}

    # PAAR-120: per-matter UnifiedApplicationReview status rollup (content-free).
    matter_status = build_portfolio_matter_status(
        state,
        application_numbers=seed_apps or None,
        include_orphans=not seed_apps,
    )
    review_status_rows: list[dict[str, Any]] = []
    for matter in matter_status.get("matters") or []:
        if not isinstance(matter, Mapping):
            continue
        rev = matter.get("review") or matter.get("unified_review") or {}
        review_status_rows.append(
            {
                "application_number": matter.get("application_number"),
                "present": bool(rev.get("present")),
                "path": rev.get("path"),
                "review_id": rev.get("review_id"),
                "disposition": rev.get("disposition") or matter.get("disposition"),
                "risk_tier": matter.get("risk_tier") or rev.get("risk_tier"),
                "conformance_status": matter.get("conformance_status")
                or rev.get("conformance_status"),
                "open_human_item_count": rev.get("open_human_item_count")
                or len(matter.get("open_human_items") or []),
                "open_human_items": list(
                    matter.get("open_human_items") or rev.get("open_human_items") or []
                )[:_MATTER_STATUS_MAX_HUMAN_ITEMS],
                "content_digest": rev.get("content_digest"),
                "generated_at_utc": rev.get("generated_at_utc"),
            }
        )

    return _matter_status_redact(
        {
            "schema": "patlaw-portfolio-dashboard-v1",
            "generated_at_utc": utc_now_iso(),
            "state_root": str(state),
            "seed": seed_payload,
            "last_review": review_summary,
            "review_status": {
                "schema": "paar-portfolio-review-status-v1",
                "matter_count": len(review_status_rows),
                "matters": review_status_rows,
                "totals": matter_status.get("totals") or {},
                "disclaimer": MATTER_STATUS_DISCLAIMER,
            },
            "public_documents": summarize_public_documents(docs_root)
            if docs_root.exists()
            else {"application_count": 0, "documents_root": str(docs_root)},
            "exports": export_dirs,
            "private_inbox": inbox_dirs,
            "schedule": schedule,
            "next_steps": [
                "keep-only / confirm your real application numbers",
                "refresh --with-documents for confirmed public wrappers",
                "drop Patent Center downloads into private_inbox/<app>/ then inbox-import",
                "attended-export for interactive private retrieval when needed",
                "run unified application review then matter-status for risk/conformance",
            ],
        }
    )


def _inbox_folder_status(folder: Path) -> dict[str, Any]:
    files = [
        p
        for p in folder.rglob("*")
        if p.is_file()
        and p.name
        not in {
            "export_manifest.json",
            "authorization.json",
            ".DS_Store",
            "READY",
            "IMPORTED",
            ".importing",
        }
        and not p.name.startswith(".")
    ]
    mtimes = []
    for path in files:
        try:
            mtimes.append(path.stat().st_mtime)
        except OSError:
            continue
    newest = max(mtimes) if mtimes else None
    age_seconds = (time.time() - newest) if newest is not None else None
    return {
        "application_number": folder.name,
        "path": str(folder),
        "file_count": len(files),
        "has_ready_marker": (folder / "READY").is_file(),
        "already_imported": (folder / "IMPORTED").is_file(),
        "sealed": (folder / "export_manifest.json").is_file(),
        "newest_mtime_age_seconds": age_seconds,
        "stable": bool(age_seconds is not None and age_seconds >= 15.0 and files),
    }


def scan_private_inbox(inbox_root: Path) -> list[dict[str, Any]]:
    root = Path(inbox_root)
    if not root.is_dir():
        return []
    return [
        _inbox_folder_status(child)
        for child in sorted(root.iterdir())
        if child.is_dir()
    ]


def import_ready_inbox_folders(
    inbox_root: Path,
    *,
    tenant_id: str,
    authorizing_user: str,
    store_root: Path,
    require_ready_marker: bool = False,
    min_stable_seconds: float = 15.0,
    classification: str = DisclosureClassification.CONFIDENTIAL_APPLICATION.value,
) -> dict[str, Any]:
    """Seal + import private inbox folders that look ready.

    A folder is ready when it has files and either:
    * contains a ``READY`` marker file, or
    * newest file mtime is at least *min_stable_seconds* old (download settled).

    Skips folders already marked ``IMPORTED`` unless files changed (no IMPORTED).
    """
    assert_operator_capability("import_user_authorized_export")
    root = Path(inbox_root)
    root.mkdir(parents=True, exist_ok=True)
    imported: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for status in scan_private_inbox(root):
        folder = Path(status["path"])
        app = str(status["application_number"])
        if status.get("already_imported"):
            skipped.append({**status, "reason": "already_imported"})
            continue
        if status.get("file_count", 0) <= 0:
            skipped.append({**status, "reason": "empty"})
            continue
        ready = bool(status.get("has_ready_marker"))
        stable = bool(status.get("stable"))
        age = status.get("newest_mtime_age_seconds")
        if require_ready_marker and not ready:
            skipped.append({**status, "reason": "waiting_for_READY_marker"})
            continue
        if not ready and not (
            stable
            and age is not None
            and float(age) >= float(min_stable_seconds)
        ):
            skipped.append({**status, "reason": "not_stable_yet"})
            continue
        try:
            result = import_export_folder(
                folder,
                tenant_id=tenant_id,
                application_number=app,
                authorizing_user=authorizing_user,
                store_root=store_root,
                classification=classification,
            )
            (folder / "IMPORTED").write_text(
                json.dumps(
                    {
                        "imported_at_utc": utc_now_iso(),
                        "application_number": app,
                        "tenant_id": tenant_id,
                    },
                    indent=2,
                )
                + "\n"
            )
            imported.append(
                {
                    "application_number": app,
                    "path": str(folder),
                    "ok": True,
                    "result": result,
                }
            )
        except Exception as exc:  # noqa: BLE001
            skipped.append(
                {
                    **status,
                    "reason": "import_failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:400],
                }
            )

    return {
        "schema": "patlaw-private-inbox-import-v1",
        "generated_at_utc": utc_now_iso(),
        "inbox_root": str(root),
        "imported_count": len(imported),
        "skipped_count": len(skipped),
        "imported": imported,
        "skipped": skipped,
    }


def keep_only_matters(
    seed: PortfolioSeed,
    application_numbers: Iterable[str],
    *,
    mark_confirmed: bool = True,
) -> tuple[PortfolioSeed, list[str]]:
    """Keep only listed apps; optionally mark them confirmed. Returns (seed, removed)."""
    keep = {
        normalize_application_number_token(a) for a in application_numbers if str(a).strip()
    }
    if not keep:
        raise PortfolioAutomationError(
            "keep-only requires at least one application number",
            code="missing_application_numbers",
        )
    kept: list[PortfolioMatter] = []
    removed: list[str] = []
    for matter in seed.matters:
        key = normalize_application_number_token(matter.application_number)
        if key in keep:
            ownership = (
                "confirmed_operator" if mark_confirmed else matter.ownership
            )
            kept.append(
                PortfolioMatter(
                    application_number=matter.application_number,
                    title=matter.title,
                    applicant=matter.applicant,
                    filing_date=matter.filing_date,
                    status_odp_search=matter.status_odp_search,
                    ownership=ownership,
                    match_basis=matter.match_basis,
                    labels=dict(matter.labels),
                )
            )
        else:
            removed.append(matter.application_number)
    # Also add any keep IDs that were not already in the seed as stubs.
    present = {
        normalize_application_number_token(m.application_number) for m in kept
    }
    for raw in application_numbers:
        key = normalize_application_number_token(raw)
        if key not in present:
            kept.append(
                PortfolioMatter(
                    application_number=str(raw).strip(),
                    ownership="confirmed_operator" if mark_confirmed else "manual",
                    match_basis="operator_keep_only",
                )
            )
            present.add(key)
    seed.matters = kept
    return seed, removed


__all__ = [
    "ALLOWED_OPERATOR_CAPABILITIES",
    "FORBIDDEN_OPERATOR_CAPABILITIES",
    "ForbiddenOperatorCapabilityError",
    "MATTER_STATUS_DISCLAIMER",
    "MATTER_STATUS_SCHEMA",
    "UNIFIED_APPLICATION_REVIEW_SCHEMA",
    "PortfolioAutomationError",
    "PortfolioMatter",
    "PortfolioSeed",
    "assert_operator_capability",
    "build_export_manifest_from_folder",
    "build_import_authorization",
    "build_portfolio_dashboard",
    "build_portfolio_matter_status",
    "confirm_ownership",
    "default_state_root",
    "discover_public_by_inventor",
    "drop_matters",
    "import_export_folder",
    "import_ready_inbox_folders",
    "inventorf_phrase_query",
    "keep_only_matters",
    "load_portfolio_seed",
    "merge_matters",
    "save_portfolio_seed",
    "scan_private_inbox",
    "summarize_matter_status",
    "summarize_public_documents",
    "sync_public_documents_batch",
    "sync_public_status_batch",
    "utc_now_iso",
    "write_export_package_sidecar",
]
