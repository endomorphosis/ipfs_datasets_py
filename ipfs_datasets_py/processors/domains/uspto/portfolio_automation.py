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


def sync_public_status_batch(
    seed: PortfolioSeed,
    *,
    store_root: Path,
    force_refresh: bool = True,
    sleep_seconds: float = 2.0,
    credential_ref: str | None = None,
) -> dict[str, Any]:
    """Refresh public ODP status for every matter in *seed*."""
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
        entry: dict[str, Any] = {
            "application_number": app,
            "title": matter.title,
            "ownership": matter.ownership,
            "applicant": matter.applicant,
            "filing_date": matter.filing_date,
        }
        try:
            result = runtime.status_processor.sync(
                app,
                matter_id=f"matter:{app}",
                force_refresh=force_refresh,
            )
            payload = result.to_dict() if hasattr(result, "to_dict") else {}
            entry["ok"] = True
            entry["provider_kind"] = payload.get("provider_kind")
            entry["provider_status_code"] = payload.get("provider_status_code")
            entry["outcome"] = payload.get("outcome")
            freshness = payload.get("freshness") or {}
            if isinstance(freshness, Mapping):
                entry["freshness_class"] = freshness.get("freshness_class")
            snap = payload.get("snapshot") or {}
            raw = {}
            status_blob: dict[str, Any] = {}
            if isinstance(snap, Mapping):
                raw = snap.get("raw_application_meta") or {}
                for key in ("status", "normalized_status", "application_status"):
                    nested = snap.get(key)
                    if isinstance(nested, Mapping):
                        status_blob = dict(nested)
                        break
                # Some snapshots embed status fields at top level.
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
            if isinstance(raw, Mapping):
                entry["status_code"] = status_blob.get("status_code") or raw.get(
                    "applicationStatusCode"
                )
                entry["status_text"] = status_blob.get("status_text") or raw.get(
                    "applicationStatusDescriptionText"
                )
                entry["entity_status"] = status_blob.get("entity_status")
                entry["patent_number"] = raw.get("patentNumber")
            else:
                entry["status_code"] = status_blob.get("status_code")
                entry["status_text"] = status_blob.get("status_text")
                entry["entity_status"] = status_blob.get("entity_status")
        except Exception as exc:  # noqa: BLE001 — operator batch continues
            entry["ok"] = False
            entry["error_type"] = type(exc).__name__
            entry["error"] = str(exc)[:400]
        reviews.append(entry)

    report = {
        "schema": "patlaw-public-status-review-v1",
        "tenant_id": seed.tenant_id,
        "generated_at_utc": utc_now_iso(),
        "credential_ref": ref,
        "candidate_count": len(seed.matters),
        "success_count": sum(1 for r in reviews if r.get("ok")),
        "failure_count": sum(1 for r in reviews if not r.get("ok")),
        "reviews_compact": reviews,
        "next_steps": [
            "Confirm candidate ownership (same-name inventors exist).",
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
    "confirm_ownership",
    "default_state_root",
    "discover_public_by_inventor",
    "drop_matters",
    "import_export_folder",
    "inventorf_phrase_query",
    "keep_only_matters",
    "load_portfolio_seed",
    "merge_matters",
    "save_portfolio_seed",
    "sync_public_status_batch",
    "utc_now_iso",
    "write_export_package_sidecar",
]
