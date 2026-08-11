"""Operator portfolio automation helpers (public ODP + authorized private import).

This module automates **review prep**, not legal submission:

* Discover candidate public applications via ODP search
* Maintain a local portfolio seed
* Batch-refresh public status through production runtime bootstrap
* Build Patent Center export manifests from a local download folder
* Drive authorized ``import-private`` into a tenant store

It never accepts Patent Center passwords, MFA secrets, session cookies as
CLI args, or signs/pays/files. Browser automation lives in the attended ops
script and only produces local export packages for this import path.
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
DEFAULT_TENANT_ID: Final = "operator-default"
DEFAULT_INVENTOR_QUERY_FIELD: Final = (
    "applicationMetaData.inventorBag.inventorNameText"
)

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


def build_portfolio_dashboard(state_root: Path) -> dict[str, Any]:
    """Aggregate seed, last review, public docs, exports, and schedule status."""
    state = Path(state_root)
    seed_path = state / "portfolio_seed.json"
    review_path = state / "public_status_review.json"
    docs_root = state / "public_docs"
    exports_dir = state / "exports"
    inbox_dir = state / "private_inbox"
    schedule_manifest = state / "schedule" / "install_manifest.json"

    seed_payload: dict[str, Any] | None = None
    if seed_path.is_file():
        seed = load_portfolio_seed(seed_path)
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

    return {
        "schema": "patlaw-portfolio-dashboard-v1",
        "generated_at_utc": utc_now_iso(),
        "state_root": str(state),
        "seed": seed_payload,
        "last_review": review_summary,
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
        ],
    }


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
    "PortfolioAutomationError",
    "PortfolioMatter",
    "PortfolioSeed",
    "assert_operator_capability",
    "build_export_manifest_from_folder",
    "build_import_authorization",
    "build_portfolio_dashboard",
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
    "summarize_public_documents",
    "sync_public_documents_batch",
    "sync_public_status_batch",
    "utc_now_iso",
    "write_export_package_sidecar",
]
