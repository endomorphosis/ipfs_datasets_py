"""Download Patent Center messages + correspondence using a saved login session.

What this exports
----------------
Account-level (Workbench-adjacent):
  * System alert messages (``/manage/public/v1/alert-messages``)
  * Customer numbers associated with the logged-in user
  * Access status
  * Best-effort Workbench correspondence/messages endpoints (often need
    broader OAuth scopes than application-read; failures are recorded, not fatal)

Per application (official IFW correspondence):
  * IFW document inventory (directionCategory INCOMING/OUTGOING)
  * Correspondence addresses
  * Application bibliographic metadata
  * Welcome-letter metadata when available
  * PDF binaries via private preview:
    ``/retrieval/private/v2/applications/{app}/documents/{id}?type=pdf``
  * Optional public ODP PDF fallback when ``USPTO_ODP_API_KEY`` is set

Constraints
-----------
* Never signs, pays, or submits.
* Tokens stay in the browser session and are never written to receipts.
* Requires a saved Playwright storage_state (``import-firefox`` or login).
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from ipfs_datasets_py.processors.domains.uspto.auth.login_session import (
    LoginError,
    load_session_status,
    session_path,
)
from ipfs_datasets_py.processors.domains.uspto.auth.patent_center_export_client import (
    PATENT_CENTER_URL,
    _browser_fetch,
    _download_binary_request,
    _download_via_odp,
    _ensure_sso,
    _extract_ifw_docs,
    _is_json_body,
    _odp_api_key,
    _read_session_tokens,
    _rid,
    _safe_name,
    _save_json,
)
from ipfs_datasets_py.processors.domains.uspto.portfolio_automation import (
    PortfolioAutomationError,
    default_state_root,
    utc_now_iso,
)

MESSAGES_SCHEMA = "patlaw-patent-center-messages-export-v1"

# Account-level GETs that do not require an application number.
_ACCOUNT_GET_ENDPOINTS: tuple[tuple[str, str], ...] = (
    ("alert_messages", "/manage/public/v1/alert-messages?rid={rid}"),
    ("access_status", "/manage/private/access/status?rid={rid}"),
    ("customers", "/retrieval/private/v1/customers?rid={rid}"),
    ("private_config", "/retrieval/private/v1/config?rid={rid}"),
)

# Workbench-style endpoints. Many return 401 "Token did not have necessary
# scope" for application-only OAuth grants; we still attempt and record.
_WORKBENCH_GET_ENDPOINTS: tuple[tuple[str, str], ...] = (
    (
        "workbench_correspondence",
        "/retrieval/private/v1/workbench/correspondence?start=0&rows=100&rid={rid}",
    ),
    (
        "workbench_messages",
        "/retrieval/private/v1/workbench/messages?start=0&rows=100&rid={rid}",
    ),
    (
        "workbench_applications",
        "/retrieval/private/v1/workbench/applications?start=0&rows=100&rid={rid}",
    ),
    ("messages", "/retrieval/private/v1/messages?start=0&rows=100&rid={rid}"),
    (
        "correspondence",
        "/retrieval/private/v1/correspondence?start=0&rows=100&rid={rid}",
    ),
    ("eoa", "/retrieval/private/v1/eoa?start=0&rows=100&rid={rid}"),
    (
        "e_office_action",
        "/retrieval/private/v1/eOfficeAction?start=0&rows=100&rid={rid}",
    ),
    ("notifications", "/retrieval/private/v1/notifications?rid={rid}"),
)

_APP_GET_ENDPOINTS: tuple[tuple[str, str], ...] = (
    (
        "application_data",
        "/retrieval/private/v3/application/data"
        "?applicationNumberText={app}&rid={rid}",
    ),
    (
        "application_data_correspondence",
        "/retrieval/private/v3/application/data"
        "?applicationNumberText={app}&correspondenceIndicator=true&rid={rid}",
    ),
    (
        "ifw_document_inventory",
        "/retrieval/private/v1/applications/sdwp/external/metadata/{app}?rid={rid}",
    ),
    (
        "addresses",
        "/retrieval/private/v2/applications/{app}/addresses?rid={rid}",
    ),
    (
        "welcome_letter",
        "/retrieval/private/application/data/welcomeletter"
        "?applicationNumberText={app}&rid={rid}",
    ),
    (
        "egrant_metadata",
        "/retrieval/private/v1/applications/egrant/metadata/{app}?rid={rid}",
    ),
    (
        "transaction_history",
        "/retrieval/private/v1/applications/{app}/transaction-history?rid={rid}",
    ),
)


@dataclass
class MessagesExportResult:
    schema: str = MESSAGES_SCHEMA
    ok: bool = False
    export_dir: str = ""
    logged_in: bool = False
    tokens_present: bool = False
    application_numbers: list[str] = field(default_factory=list)
    account_metadata: list[str] = field(default_factory=list)
    workbench_status: dict[str, Any] = field(default_factory=dict)
    applications: dict[str, Any] = field(default_factory=dict)
    files: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    message: str = ""
    correspondence_document_count: int = 0
    pdf_downloads: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "ok": self.ok,
            "export_dir": self.export_dir,
            "logged_in": self.logged_in,
            "tokens_present": self.tokens_present,
            "application_numbers": list(self.application_numbers),
            "account_metadata": list(self.account_metadata),
            "workbench_status": dict(self.workbench_status),
            "applications": dict(self.applications),
            "file_count": len(self.files),
            "files": list(self.files),
            "correspondence_document_count": self.correspondence_document_count,
            "pdf_downloads": self.pdf_downloads,
            "errors": list(self.errors),
            "message": self.message,
            "generated_at_utc": utc_now_iso(),
        }


def _normalize_app(value: str) -> str:
    return str(value or "").strip().replace(",", "").replace(" ", "")


def _direction_filter(docs: Sequence[Mapping[str, Any]], direction: str) -> list[dict[str, Any]]:
    """Filter IFW docs by directionCategory.

    direction: 'all' | 'outgoing' | 'incoming' | 'correspondence'
    'correspondence' prefers OUTGOING USPTO mailings (office actions, notices)
    plus any doc whose code/description looks like correspondence.
    """
    direction = (direction or "all").strip().lower()
    out: list[dict[str, Any]] = []
    corr_codes = {
        "NOA",
        "CTFR",
        "CTNF",
        "CTRS",
        "EXIN",
        "ISSUE.NTF",
        "EGRANT.NTF",
        "WELCOME.LET",
        "NTC.PUB",
        "SRNT",
        "SRFW",
        "IIFW",
        "BIB",
        "892",
        "1449",
        "N417",
        "APP.FILE.REC",
    }
    for d in docs:
        if not isinstance(d, Mapping):
            continue
        cat = str(d.get("directionCategory") or "").upper()
        code = str(d.get("documentCode") or "").upper()
        desc = str(d.get("documentDescription") or "").lower()
        if direction == "all":
            out.append(dict(d))
        elif direction == "outgoing" and cat == "OUTGOING":
            out.append(dict(d))
        elif direction == "incoming" and cat == "INCOMING":
            out.append(dict(d))
        elif direction == "correspondence":
            if cat == "OUTGOING" or code in corr_codes or "correspond" in desc:
                out.append(dict(d))
    return out


def _download_private_pdf(
    page: Any,
    application_number: str,
    document_id: str,
    dest: Path,
    *,
    tokens: Mapping[str, str],
) -> bool:
    """Download one IFW PDF via private Patent Center preview endpoints."""
    app = _normalize_app(application_number)
    doc_id = str(document_id or "").strip()
    if not app or not doc_id:
        return False
    candidates = (
        f"{PATENT_CENTER_URL}/retrieval/private/v2/applications/{app}/documents/"
        f"{doc_id}?type=pdf&rid={_rid()}",
        f"{PATENT_CENTER_URL}/retrieval/private/v2/applications/{app}/documents/"
        f"{doc_id}?type=PDF&rid={_rid()}",
        f"{PATENT_CENTER_URL}/retrieval/private/v1/applications/{app}/documents/"
        f"{doc_id}?type=pdf&rid={_rid()}",
    )
    for url in candidates:
        if _download_binary_request(page, url, dest, tokens=tokens):
            try:
                if dest.is_file() and dest.stat().st_size > 64:
                    # Prefer real PDFs; reject HTML/JSON error bodies already
                    # filtered in _download_binary_request.
                    head = dest.read_bytes()[:5]
                    if head.startswith(b"%PDF") or dest.stat().st_size > 1000:
                        return True
            except OSError:
                pass
            try:
                dest.unlink(missing_ok=True)
            except OSError:
                pass
    return False


def export_messages_and_correspondence(
    application_numbers: Sequence[str] | None = None,
    *,
    state_root: Path | None = None,
    session_name: str = "patent_center",
    export_dir: Path | None = None,
    headless: bool = True,
    download_pdfs: bool = True,
    direction: str = "all",
    max_pdf_downloads: int = 200,
    use_odp_fallback: bool = True,
) -> MessagesExportResult:
    """Export Patent Center alert messages + application correspondence.

    Parameters
    ----------
    application_numbers:
        Apps to pull IFW correspondence for. Empty → account-level only.
    direction:
        Which IFW docs to download. Default ``all`` includes every PDF in the
        IFW inventory (USPTO OUTGOING mailings + applicant INCOMING filings).
        Use ``outgoing`` for USPTO-only mailings, ``incoming`` for filings,
        or ``correspondence`` for a notice-code subset.
    """
    root = Path(state_root) if state_root else default_state_root()
    status = load_session_status(root, name=session_name)
    if not status.present:
        raise LoginError(
            "no saved Patent Center session; run portfolio_cli import-firefox "
            "or login first",
            code="no_session",
        )
    storage = session_path(root, name=session_name)
    dest = (
        Path(export_dir)
        if export_dir
        else root / "exports" / "messages_correspondence"
    )
    dest.mkdir(parents=True, exist_ok=True)
    account_dir = dest / "account"
    account_dir.mkdir(exist_ok=True)
    files_dir = dest / "files"
    files_dir.mkdir(exist_ok=True)

    apps = [
        _normalize_app(a)
        for a in (application_numbers or [])
        if _normalize_app(a)
    ]
    result = MessagesExportResult(
        export_dir=str(dest),
        application_numbers=list(apps),
    )

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise PortfolioAutomationError(
            "playwright required for messages/correspondence export",
            code="playwright_missing",
        ) from exc

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=bool(headless),
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            storage_state=str(storage),
            accept_downloads=True,
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
        )
        page = context.new_page()
        try:
            page.goto(
                PATENT_CENTER_URL + "/",
                wait_until="networkidle",
                timeout=120_000,
            )
            logged_in = _ensure_sso(page)
            result.logged_in = logged_in
            if not logged_in:
                result.message = "patent_center_sso_failed"
                result.errors.append(
                    "userLoggedIn remained false after SSO attempts"
                )
                _save_json(dest / "export_receipt.json", result.to_dict())
                return result

            context.storage_state(path=str(storage))
            tokens = _read_session_tokens(page)
            result.tokens_present = bool(tokens.get("bearer"))
            if not tokens.get("bearer"):
                result.errors.append(
                    "no_bearer_token: re-import Firefox after reloading "
                    "patentcenter.uspto.gov so OktaAccessToken is fresh"
                )

            token_meta = {
                "bearer": bool(tokens.get("bearer")),
                "xauth": bool(tokens.get("xauth")),
                "bearer_len": len(tokens.get("bearer") or ""),
                "xauth_len": len(tokens.get("xauth") or ""),
            }
            _save_json(account_dir / "token_presence.json", token_meta)

            # --- Account-level ---
            for key, template in _ACCOUNT_GET_ENDPOINTS:
                path = template.format(rid=_rid())
                status_code, body = _browser_fetch(page, path, tokens=tokens)
                index = {"status": status_code, "ok": status_code == 200}
                if status_code == 200 and _is_json_body(body):
                    outp = account_dir / f"{key}.json"
                    _save_json(outp, body)
                    result.account_metadata.append(str(outp))
                    index["body_saved"] = True
                elif status_code:
                    index["error"] = (
                        body if isinstance(body, (dict, list, str)) else None
                    )
                result.workbench_status[key] = index

            # --- Workbench / messages (best-effort) ---
            for key, template in _WORKBENCH_GET_ENDPOINTS:
                path = template.format(rid=_rid())
                status_code, body = _browser_fetch(page, path, tokens=tokens)
                entry: dict[str, Any] = {
                    "status": status_code,
                    "ok": status_code == 200,
                }
                if status_code == 200 and _is_json_body(body):
                    outp = account_dir / f"{key}.json"
                    _save_json(outp, body)
                    result.account_metadata.append(str(outp))
                    entry["body_saved"] = True
                elif status_code == 401:
                    msg = ""
                    if isinstance(body, Mapping):
                        msg = str(body.get("message") or "")
                    entry["error"] = msg or "unauthorized"
                    if "scope" in msg.lower():
                        entry["note"] = (
                            "token lacks workbench/messages OAuth scope; "
                            "application IFW correspondence still exports"
                        )
                elif status_code:
                    entry["error"] = (
                        body if isinstance(body, (dict, list, str)) else None
                    )
                result.workbench_status[key] = entry

            # --- Per-application correspondence ---
            pdf_budget = max(0, int(max_pdf_downloads))
            for app in apps:
                app_dir = dest / "applications" / app
                meta_dir = app_dir / "metadata"
                app_files = app_dir / "files"
                meta_dir.mkdir(parents=True, exist_ok=True)
                app_files.mkdir(parents=True, exist_ok=True)
                app_result: dict[str, Any] = {
                    "application_number": app,
                    "metadata": [],
                    "documents": 0,
                    "pdf_downloads": 0,
                    "errors": [],
                }

                # Refresh tokens after app navigation (mints SPA state).
                try:
                    page.goto(
                        f"{PATENT_CENTER_URL}/applications/{app}",
                        wait_until="networkidle",
                        timeout=120_000,
                    )
                    page.wait_for_timeout(1500)
                except Exception as exc:  # noqa: BLE001
                    app_result["errors"].append(
                        f"nav:{type(exc).__name__}"
                    )
                tokens = _read_session_tokens(page) or tokens
                result.tokens_present = bool(
                    result.tokens_present or tokens.get("bearer")
                )

                for key, template in _APP_GET_ENDPOINTS:
                    path = template.format(app=app, rid=_rid())
                    status_code, body = _browser_fetch(
                        page, path, tokens=tokens
                    )
                    if status_code == 200 and _is_json_body(body):
                        outp = meta_dir / f"{key}.json"
                        _save_json(outp, body)
                        app_result["metadata"].append(str(outp))
                    elif status_code and status_code != 200:
                        app_result["errors"].append(
                            f"{key}:http_{status_code}"
                        )

                ifw_docs: list[dict[str, Any]] = []
                inv_path = meta_dir / "ifw_document_inventory.json"
                if inv_path.is_file():
                    try:
                        ifw_docs = _extract_ifw_docs(
                            json.loads(inv_path.read_text(encoding="utf-8"))
                        )
                    except Exception:
                        ifw_docs = []

                selected = _direction_filter(ifw_docs, direction)
                app_result["documents"] = len(selected)
                result.correspondence_document_count += len(selected)

                def _mime_set(d: Mapping[str, Any]) -> set[str]:
                    mimes = d.get("mimeTypeBag") or []
                    if isinstance(mimes, list):
                        return {str(m).upper() for m in mimes}
                    return set()

                def _has_pdf(d: Mapping[str, Any]) -> bool:
                    mimes = _mime_set(d)
                    # Empty mime bag: still try PDF download (many OUTGOING
                    # mailings are PDF-only even when mimeTypeBag is sparse).
                    return (not mimes) or ("PDF" in mimes)

                outgoing_all = [
                    d
                    for d in ifw_docs
                    if str(d.get("directionCategory") or "").upper()
                    == "OUTGOING"
                ]
                incoming_all = [
                    d
                    for d in ifw_docs
                    if str(d.get("directionCategory") or "").upper()
                    == "INCOMING"
                ]
                skipped_non_pdf = [
                    {
                        "documentIdentifier": d.get("documentIdentifier"),
                        "documentCode": d.get("documentCode"),
                        "documentDescription": d.get("documentDescription"),
                        "directionCategory": d.get("directionCategory"),
                        "mimeTypeBag": d.get("mimeTypeBag"),
                    }
                    for d in selected
                    if not _has_pdf(d)
                ]

                summary = [
                    {
                        "documentIdentifier": d.get("documentIdentifier"),
                        "documentCode": d.get("documentCode"),
                        "documentDescription": d.get("documentDescription"),
                        "directionCategory": d.get("directionCategory"),
                        "officialDate": d.get("officialDate"),
                        "mimeTypeBag": d.get("mimeTypeBag"),
                        "pageTotalQuantity": d.get("pageTotalQuantity"),
                        "will_download_pdf": _has_pdf(d),
                    }
                    for d in selected
                ]
                outp = meta_dir / "correspondence_document_summary.json"
                _save_json(
                    outp,
                    {
                        "count": len(summary),
                        "direction_filter": direction,
                        "ifw_total": len(ifw_docs),
                        "outgoing_uspto_mailings": len(outgoing_all),
                        "incoming_filings": len(incoming_all),
                        "selected_pdf_candidates": sum(
                            1 for d in selected if _has_pdf(d)
                        ),
                        "skipped_non_pdf_count": len(skipped_non_pdf),
                        "skipped_non_pdf": skipped_non_pdf,
                        "documents": summary,
                    },
                )
                app_result["metadata"].append(str(outp))
                app_result["outgoing_uspto_mailings"] = len(outgoing_all)
                app_result["incoming_filings"] = len(incoming_all)

                if download_pdfs and selected and pdf_budget > 0:
                    for doc in selected:
                        if pdf_budget <= 0:
                            break
                        doc_id = str(
                            doc.get("documentIdentifier") or ""
                        ).strip()
                        code = _safe_name(
                            str(doc.get("documentCode") or "DOC")
                        )
                        if not doc_id:
                            continue
                        if not _has_pdf(doc):
                            # Listed in summary skipped_non_pdf; not an error.
                            continue
                        dest_file = (
                            app_files / f"{code}_{_safe_name(doc_id)}.pdf"
                        )
                        # Also mirror under top-level files/ for easy import.
                        mirror = (
                            files_dir / f"{app}_{code}_{_safe_name(doc_id)}.pdf"
                        )
                        if dest_file.exists() and dest_file.stat().st_size > 0:
                            app_result["pdf_downloads"] += 1
                            result.pdf_downloads += 1
                            if str(dest_file) not in result.files:
                                result.files.append(str(dest_file))
                            continue

                        got = _download_private_pdf(
                            page,
                            app,
                            doc_id,
                            dest_file,
                            tokens=tokens,
                        )
                        if (
                            not got
                            and use_odp_fallback
                            and _odp_api_key()
                        ):
                            got = _download_via_odp(app, doc_id, dest_file)

                        if got:
                            pdf_budget -= 1
                            app_result["pdf_downloads"] += 1
                            result.pdf_downloads += 1
                            result.files.append(str(dest_file))
                            try:
                                if not mirror.exists():
                                    mirror.write_bytes(dest_file.read_bytes())
                                    result.files.append(str(mirror))
                            except OSError:
                                pass
                        else:
                            app_result["errors"].append(
                                f"pdf_download_failed:{doc_id}"
                            )

                result.applications[app] = app_result

            result.ok = bool(
                result.account_metadata
                or result.correspondence_document_count
                or result.files
                or any(
                    (v or {}).get("ok")
                    for v in result.workbench_status.values()
                )
            )
            if result.ok:
                result.message = "messages_correspondence_export_complete"
            else:
                result.message = "export_incomplete"
                if not result.errors:
                    result.errors.append("no_metadata_or_files_saved")

            context.storage_state(path=str(storage))
            _save_json(dest / "export_receipt.json", result.to_dict())
            _save_json(
                dest / "export_index.json",
                {
                    "schema": MESSAGES_SCHEMA,
                    "generated_at_utc": utc_now_iso(),
                    "workbench_status": result.workbench_status,
                    "applications": {
                        k: {
                            "documents": v.get("documents"),
                            "pdf_downloads": v.get("pdf_downloads"),
                            "metadata_count": len(v.get("metadata") or []),
                            "error_count": len(v.get("errors") or []),
                        }
                        for k, v in result.applications.items()
                    },
                },
            )
            return result
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"{type(exc).__name__}:{exc}")
            result.message = "export_failed"
            try:
                _save_json(dest / "export_receipt.json", result.to_dict())
            except Exception:
                pass
            return result
        finally:
            context.close()
            browser.close()


__all__ = [
    "MessagesExportResult",
    "export_messages_and_correspondence",
]
