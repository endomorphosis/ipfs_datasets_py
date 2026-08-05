"""Authenticated Patent Center export via SSO + retrieval APIs / UI.

Flow
----
1. Load Playwright ``storage_state`` from the operator login session.
2. Open Patent Center and complete SSO until ``userLoggedIn: true``.
3. Read in-page tokens (``sessionStorage.accessToken_default`` +
   ``X-AUTH-TOKEN``) that private retrieval routes require.
4. Navigate to the application and IFW views so the SPA hydrates.
5. Fetch private + public metadata (bib data, eGrant, addresses, fees, IFW
   inventory via ``sdwp/external/metadata``).
6. Download eGrant PDF/XML via UI Download controls.
7. Optionally download IFW document bytes via public ODP (``USPTO_ODP_API_KEY``)
   using identifiers from the Patent Center IFW inventory.
8. Deduplicate files, write a sealed export package for ``import-private``.

This module never signs, pays, or files. Tokens stay in the browser session
and are not written to receipts or metadata sidecars.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ipfs_datasets_py.processors.domains.uspto.auth.login_session import (
    LoginError,
    load_session_status,
    session_path,
)
from ipfs_datasets_py.processors.domains.uspto.portfolio_automation import (
    PortfolioAutomationError,
    default_state_root,
    utc_now_iso,
    write_export_package_sidecar,
)

PATENT_CENTER_URL = "https://patentcenter.uspto.gov"
ODP_DOWNLOAD_BASE = "https://api.uspto.gov/api/v1/download/applications"
EXPORT_SCHEMA = "patlaw-patent-center-ui-export-v1"

# Metadata endpoints discovered against live Patent Center (2026-08).
_PRIVATE_GET_ENDPOINTS = (
    (
        "application_data",
        "/retrieval/private/v3/application/data?applicationNumberText={app}&rid={rid}",
    ),
    (
        "application_data_v2",
        "/retrieval/private/v2/application/data?applicationNumberText={app}&rid={rid}",
    ),
    (
        "egrant_metadata",
        "/retrieval/private/v1/applications/egrant/metadata/{app}?rid={rid}",
    ),
    (
        "egrant_cof_c_metadata",
        "/retrieval/private/v1/applications/eGrantAndeCofC/metadata/{app}?rid={rid}",
    ),
    (
        "addresses",
        "/retrieval/private/v2/applications/{app}/addresses?rid={rid}",
    ),
    (
        "first_action_prediction",
        "/retrieval/private/v1/first-action-prediction?applicationNumber={app}&rid={rid}",
    ),
    (
        "ifw_document_inventory",
        "/retrieval/private/v1/applications/sdwp/external/metadata/{app}?rid={rid}",
    ),
    (
        "customers",
        "/retrieval/private/v1/customers?rid={rid}",
    ),
    (
        "sdwp_welcomeletter",
        "/retrieval/private/application/data/welcomeletter"
        "?applicationNumberText={app}&rid={rid}",
    ),
)

_PUBLIC_GET_ENDPOINTS = (
    (
        "public_application_data",
        "/retrieval/public/v2/application/data?applicationNumberText={app}&rid={rid}",
    ),
    (
        "public_egrant_metadata",
        "/retrieval/public/v1/applications/egrant/metadata/{app}?rid={rid}",
    ),
)


@dataclass
class PatentCenterExportResult:
    schema: str = EXPORT_SCHEMA
    ok: bool = False
    application_number: str = ""
    export_dir: str = ""
    logged_in: bool = False
    files: list[str] = field(default_factory=list)
    metadata_paths: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    message: str = ""
    ifw_document_count: int = 0
    odp_downloads: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "ok": self.ok,
            "application_number": self.application_number,
            "export_dir": self.export_dir,
            "logged_in": self.logged_in,
            "file_count": len(self.files),
            "files": list(self.files),
            "metadata_paths": list(self.metadata_paths),
            "ifw_document_count": self.ifw_document_count,
            "odp_downloads": self.odp_downloads,
            "errors": list(self.errors),
            "message": self.message,
            "generated_at_utc": utc_now_iso(),
        }


def _rid() -> str:
    return str(uuid.uuid4())


def _safe_name(name: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", str(name or "file"))
    return (text[:180] or "file").strip("._") or "file"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_json_body(body: Any) -> bool:
    if body is None:
        return False
    if isinstance(body, (dict, list)):
        return True
    if isinstance(body, str):
        stripped = body.lstrip()
        return stripped.startswith("{") or stripped.startswith("[")
    return False


def _ensure_sso(page: Any, *, attempts: int = 5) -> bool:
    for _ in range(max(1, attempts)):
        try:
            resp = page.request.get(
                f"{PATENT_CENTER_URL}/manage/public/auth/check?rid={_rid()}"
            )
            text = resp.text()
            if '"userLoggedIn":true' in text.replace(" ", ""):
                return True
        except Exception:
            pass
        try:
            page.goto(
                PATENT_CENTER_URL + "/",
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            page.wait_for_timeout(1500)
            for sel in (
                "text=Sign in",
                "a:has-text('Sign in')",
                "button:has-text('Sign in')",
            ):
                loc = page.locator(sel)
                if loc.count() and loc.first.is_visible():
                    loc.first.click(timeout=5000)
                    break
        except Exception:
            pass
        page.wait_for_timeout(7000)
    try:
        resp = page.request.get(
            f"{PATENT_CENTER_URL}/manage/public/auth/check?rid={_rid()}"
        )
        return '"userLoggedIn":true' in resp.text().replace(" ", "")
    except Exception:
        return False


def _read_session_tokens(page: Any) -> dict[str, str]:
    """Pull SPA tokens required by private retrieval routes."""
    try:
        tokens = page.evaluate(
            """() => ({
              bearer: sessionStorage.getItem('accessToken_default') || '',
              xauth: sessionStorage.getItem('X-AUTH-TOKEN') || '',
            })"""
        )
    except Exception:
        return {"bearer": "", "xauth": ""}
    if not isinstance(tokens, dict):
        return {"bearer": "", "xauth": ""}
    return {
        "bearer": str(tokens.get("bearer") or ""),
        "xauth": str(tokens.get("xauth") or ""),
    }


def _browser_fetch(
    page: Any,
    path: str,
    *,
    method: str = "GET",
    body: Any | None = None,
    tokens: Mapping[str, str] | None = None,
    accept: str = "application/json",
) -> tuple[int, Any]:
    """In-page fetch with optional Bearer + X-AUTH-TOKEN headers."""
    payload = {
        "path": path,
        "method": method,
        "body": body,
        "bearer": (tokens or {}).get("bearer") or "",
        "xauth": (tokens or {}).get("xauth") or "",
        "accept": accept,
    }
    result = page.evaluate(
        """async (payload) => {
          try {
            const headers = {
              'Accept': payload.accept || 'application/json',
            };
            if (payload.bearer) {
              headers['Authorization'] = payload.bearer.startsWith('Bearer ')
                ? payload.bearer
                : ('Bearer ' + payload.bearer);
            }
            if (payload.xauth) {
              headers['X-AUTH-TOKEN'] = payload.xauth;
            }
            const opts = {
              method: payload.method || 'GET',
              credentials: 'include',
              headers,
            };
            if (payload.body !== null && payload.body !== undefined) {
              headers['Content-Type'] = 'application/json';
              opts.body = JSON.stringify(payload.body);
            }
            const r = await fetch(payload.path, opts);
            const ct = r.headers.get('content-type') || '';
            if (ct.includes('json') || (payload.accept || '').includes('json')) {
              const t = await r.text();
              let parsed = t;
              try { parsed = JSON.parse(t); } catch (e) {}
              return {status: r.status, ct, body: parsed};
            }
            const buf = await r.arrayBuffer();
            const bytes = Array.from(new Uint8Array(buf));
            return {status: r.status, ct, bytes};
          } catch (e) {
            return {status: 0, err: String(e)};
          }
        }""",
        payload,
    )
    if not isinstance(result, dict):
        return 0, None
    if result.get("err"):
        return 0, {"error": result["err"]}
    if "bytes" in result and result.get("bytes") is not None:
        return int(result.get("status") or 0), bytes(result["bytes"])
    return int(result.get("status") or 0), result.get("body")


def _ui_open_application(page: Any, application_number: str) -> dict[str, Any]:
    """Open application bibliographic page (search or direct URL)."""
    app = application_number
    direct = f"{PATENT_CENTER_URL}/applications/{app}"
    try:
        page.goto(direct, wait_until="networkidle", timeout=120_000)
        page.wait_for_timeout(2500)
        body = ""
        try:
            body = page.inner_text("body")
        except Exception:
            body = ""
        if app[:5] in body.replace(",", "") or "Download" in body:
            return {
                "ok": True,
                "method": "direct",
                "url": page.url,
                "body_len": len(body),
            }
    except Exception as exc:  # noqa: BLE001
        direct_err = f"{type(exc).__name__}"
    else:
        direct_err = "not_found_on_page"

    # Fallback: global search box
    page.goto(PATENT_CENTER_URL + "/", wait_until="networkidle", timeout=120_000)
    page.wait_for_timeout(2000)
    try:
        page.get_by_text("Application number", exact=False).first.click(timeout=3000)
        page.wait_for_timeout(800)
    except Exception:
        pass

    filled = False
    for sel in (
        "input[placeholder*='Search' i]",
        "input#searchInput",
        "input[formcontrolname='searchInput']",
        "input[type='search']",
        "input[type='text']",
    ):
        loc = page.locator(sel)
        try:
            if loc.count() and loc.first.is_visible():
                loc.first.fill("")
                loc.first.fill(app)
                filled = True
                break
        except Exception:
            continue
    if not filled:
        return {
            "ok": False,
            "method": "search",
            "reason": "search_input_not_found",
            "direct_error": direct_err,
        }

    page.keyboard.press("Enter")
    page.wait_for_timeout(2000)
    for sel in (
        "button:has-text('Search')",
        "button[type='submit']",
        "button:has-text('Go')",
    ):
        try:
            loc = page.locator(sel)
            if loc.count() and loc.first.is_visible():
                loc.first.click(timeout=3000)
                break
        except Exception:
            continue
    page.wait_for_timeout(6000)
    body = ""
    try:
        body = page.inner_text("body")
    except Exception:
        body = ""
    return {
        "ok": app.replace(",", "")[:5] in body.replace(",", "")
        or "Application" in body
        or "Download" in body,
        "method": "search",
        "url": page.url,
        "body_len": len(body),
        "body_sample": body[:400],
        "direct_error": direct_err,
    }


def _ui_open_ifw(page: Any, application_number: str) -> dict[str, Any]:
    url = f"{PATENT_CENTER_URL}/applications/{application_number}/ifw/docs?application="
    try:
        page.goto(url, wait_until="networkidle", timeout=120_000)
        page.wait_for_timeout(4000)
        body = ""
        try:
            body = page.inner_text("body")
        except Exception:
            body = ""
        return {
            "ok": "Documents" in body or "Preview" in body or "IFW" in body.upper(),
            "url": page.url,
            "body_len": len(body),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}:{exc}"}


def _save_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def _download_binary_request(
    page: Any,
    url: str,
    dest: Path,
    *,
    tokens: Mapping[str, str] | None = None,
) -> bool:
    try:
        headers = {"Accept": "*/*"}
        if tokens and tokens.get("bearer"):
            b = tokens["bearer"]
            headers["Authorization"] = b if b.startswith("Bearer ") else f"Bearer {b}"
        if tokens and tokens.get("xauth"):
            headers["X-AUTH-TOKEN"] = tokens["xauth"]
        resp = page.request.get(url, headers=headers)
        if resp.status >= 400:
            return False
        body = resp.body()
        ct = (resp.headers.get("content-type") or "").lower()
        if not body:
            return False
        if "text/html" in ct or body.lstrip()[:9].lower() == b"<!doctype":
            return False
        if body[:1] in (b"{", b"[") and b"message" in body[:80]:
            return False
        dest.write_bytes(body)
        return dest.stat().st_size > 0
    except Exception:
        return False


def _odp_api_key() -> str:
    return (os.environ.get("USPTO_ODP_API_KEY") or "").strip()


def _download_via_odp(application_number: str, document_id: str, dest: Path) -> bool:
    """Download a public IFW document through ODP (follows redirect URL)."""
    key = _odp_api_key()
    if not key:
        return False
    doc_id = str(document_id or "").strip()
    if not doc_id:
        return False
    # Prefer explicit .pdf for PDF docs; ODP also accepts bare ids.
    candidates = [
        f"{ODP_DOWNLOAD_BASE}/{application_number}/{doc_id}.pdf",
        f"{ODP_DOWNLOAD_BASE}/{application_number}/{doc_id}",
    ]
    for url in candidates:
        try:
            req = Request(
                url,
                headers={
                    "X-API-KEY": key,
                    "Accept": "*/*",
                    "User-Agent": "patlaw-patent-center-export/1.0",
                },
                method="GET",
            )
            with urlopen(req, timeout=90) as resp:  # noqa: S310 — fixed USPTO host
                data = resp.read()
                ct = (resp.headers.get("Content-Type") or "").lower()
            if not data or len(data) < 64:
                continue
            if data[:1] in (b"{", b"[") and b"redirect" in data[:200].lower():
                # JSON redirect instruction
                try:
                    msg = json.loads(data.decode("utf-8", errors="replace"))
                except Exception:
                    continue
                text = str(msg.get("message") or msg)
                m = re.search(r"https://data-documents\.uspto\.gov/[^\s\"']+", text)
                if not m:
                    continue
                redir = m.group(0).rstrip(".")
                req2 = Request(
                    redir,
                    headers={"Accept": "*/*", "User-Agent": "patlaw-patent-center-export/1.0"},
                    method="GET",
                )
                with urlopen(req2, timeout=90) as resp2:  # noqa: S310
                    data = resp2.read()
                    ct = (resp2.headers.get("Content-Type") or "").lower()
            if data[:4] == b"%PDF" or "pdf" in ct or len(data) > 500:
                if data[:1] in (b"{", b"[") and len(data) < 500:
                    continue
                dest.write_bytes(data)
                return dest.stat().st_size > 0
        except (HTTPError, URLError, TimeoutError, OSError):
            continue
        except Exception:
            continue
    return False


def _extract_ifw_docs(inventory: Any) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    if isinstance(inventory, Mapping):
        bag = inventory.get("resultBag") or inventory.get("documentBag") or []
        if isinstance(bag, list):
            for item in bag:
                if isinstance(item, Mapping) and "documentBag" in item:
                    inner = item.get("documentBag") or []
                    if isinstance(inner, list):
                        for d in inner:
                            if isinstance(d, Mapping):
                                docs.append(dict(d))
                elif isinstance(item, Mapping) and item.get("documentIdentifier"):
                    docs.append(dict(item))
    elif isinstance(inventory, list):
        for d in inventory:
            if isinstance(d, Mapping):
                docs.append(dict(d))
    return docs


def _dedupe_files_dir(files_dir: Path) -> list[str]:
    """Keep unique content by sha256; drop timestamped duplicates."""
    kept: list[str] = []
    seen_hash: dict[str, Path] = {}
    # Prefer non-timestamped names first.
    paths = sorted(files_dir.iterdir(), key=lambda p: (bool(re.search(r"-\d{9,}", p.name)), p.name))
    for path in paths:
        if not path.is_file():
            continue
        digest = _sha256_file(path)
        if digest in seen_hash:
            try:
                path.unlink()
            except OSError:
                pass
            continue
        seen_hash[digest] = path
        kept.append(str(path))
    return kept


def _click_download_controls(page: Any) -> int:
    """Click visible Download / Download PDF controls; return click attempts."""
    clicks = 0
    for label in ("Download PDF", "Download eGrant", "Download"):
        try:
            loc = page.get_by_text(label, exact=False)
            count = loc.count()
            for i in range(min(count, 8)):
                el = loc.nth(i)
                try:
                    if not el.is_visible():
                        continue
                    el.click(timeout=4000)
                    clicks += 1
                    page.wait_for_timeout(2000)
                except Exception:
                    continue
        except Exception:
            continue
    return clicks


def export_application_via_patent_center(
    application_number: str,
    *,
    state_root: Path | None = None,
    session_name: str = "patent_center",
    export_dir: Path | None = None,
    authorizing_user: str = "operator:local",
    tenant_id: str = "operator-default",
    headless: bool = True,
    download_ifw_via_odp: bool = True,
    max_ifw_downloads: int = 200,
) -> PatentCenterExportResult:
    """Export one application using authenticated Patent Center automation."""
    app = str(application_number or "").strip().replace(",", "").replace(" ", "")
    if not app:
        raise PortfolioAutomationError("application_number required", code="missing_app")

    root = Path(state_root) if state_root else default_state_root()
    status = load_session_status(root, name=session_name)
    if not status.present:
        raise LoginError(
            "no saved Patent Center session; run portfolio_cli login first",
            code="no_session",
        )
    storage = session_path(root, name=session_name)
    dest = (
        Path(export_dir)
        if export_dir
        else root / "exports" / app / "patent_center_ui"
    )
    dest.mkdir(parents=True, exist_ok=True)
    meta_dir = dest / "metadata"
    meta_dir.mkdir(exist_ok=True)
    files_dir = dest / "files"
    files_dir.mkdir(exist_ok=True)

    result = PatentCenterExportResult(
        application_number=app,
        export_dir=str(dest),
    )

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise PortfolioAutomationError(
            "playwright required for Patent Center export",
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
        downloads: list[str] = []
        spa_json: dict[str, Any] = {}

        def _on_download(download: Any) -> None:
            try:
                name = _safe_name(download.suggested_filename or f"dl-{int(time.time())}")
                target = files_dir / name
                if target.exists():
                    target = files_dir / f"{target.stem}-{int(time.time())}{target.suffix}"
                download.save_as(str(target))
                downloads.append(str(target))
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"download_handler:{type(exc).__name__}")

        def _on_response(resp: Any) -> None:
            try:
                url = resp.url or ""
                if "/retrieval/" not in url or resp.status != 200:
                    return
                ct = (resp.headers.get("content-type") or "").lower()
                if "json" not in ct:
                    return
                key = url.split("?")[0].replace(PATENT_CENTER_URL, "")
                if key in spa_json:
                    return
                body = resp.json()
                spa_json[key] = body
            except Exception:
                return

        page.on("download", _on_download)
        page.on("response", _on_response)

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
                return result

            # Persist upgraded SSO cookies
            context.storage_state(path=str(storage))

            tokens = _read_session_tokens(page)
            if not tokens.get("bearer"):
                # SPA may mint tokens after app navigation.
                pass

            search = _ui_open_application(page, app)
            _save_json(meta_dir / "ui_navigation.json", search)
            page.wait_for_timeout(1500)
            tokens = _read_session_tokens(page) or tokens

            ifw_nav = _ui_open_ifw(page, app)
            _save_json(meta_dir / "ui_ifw_navigation.json", ifw_nav)
            page.wait_for_timeout(1500)
            tokens = _read_session_tokens(page) or tokens

            # Prefer app bibliographic page for eGrant download buttons.
            try:
                page.goto(
                    f"{PATENT_CENTER_URL}/applications/{app}",
                    wait_until="networkidle",
                    timeout=120_000,
                )
                page.wait_for_timeout(2000)
            except Exception:
                pass
            tokens = _read_session_tokens(page) or tokens

            metadata: dict[str, Any] = {
                "tokens_present": {
                    "bearer": bool(tokens.get("bearer")),
                    "xauth": bool(tokens.get("xauth")),
                    # lengths only — never store token values
                    "bearer_len": len(tokens.get("bearer") or ""),
                    "xauth_len": len(tokens.get("xauth") or ""),
                }
            }

            for key, template in _PRIVATE_GET_ENDPOINTS + _PUBLIC_GET_ENDPOINTS:
                path = template.format(app=app, rid=_rid())
                status_code, body = _browser_fetch(page, path, tokens=tokens)
                metadata[key] = {"status": status_code, "ok": status_code == 200}
                if status_code == 200 and _is_json_body(body):
                    outp = meta_dir / f"{key}.json"
                    _save_json(outp, body)
                    result.metadata_paths.append(str(outp))
                    metadata[key]["body_saved"] = True
                elif status_code and status_code != 200:
                    metadata[key]["error_body"] = (
                        body if isinstance(body, (dict, list, str)) else None
                    )

            # Fees need patent number when available
            patent_number = ""
            for meta_key in ("application_data", "application_data_v2", "public_application_data"):
                path = meta_dir / f"{meta_key}.json"
                if not path.is_file():
                    continue
                try:
                    app_body = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if isinstance(app_body, Mapping):
                    meta = app_body.get("applicationMetaData") or app_body
                    if isinstance(meta, Mapping):
                        patent_number = str(
                            meta.get("patentNumber")
                            or meta.get("patentNumberText")
                            or ""
                        ).replace(",", "")
                        if patent_number:
                            break
            if patent_number:
                path = (
                    f"/retrieval/private/v1/applications/{app}/fees"
                    f"?patentNumber={patent_number}&rid={_rid()}"
                )
                status_code, body = _browser_fetch(page, path, tokens=tokens)
                metadata["fees"] = {"status": status_code, "ok": status_code == 200}
                if status_code == 200 and _is_json_body(body):
                    outp = meta_dir / "fees.json"
                    _save_json(outp, body)
                    result.metadata_paths.append(str(outp))

            # Persist any SPA-captured JSON not already saved
            for spa_path, spa_body in spa_json.items():
                if not _is_json_body(spa_body):
                    continue
                name = _safe_name(spa_path.strip("/").replace("/", "_")) or "spa"
                outp = meta_dir / f"spa_{name}.json"
                if outp.exists():
                    continue
                _save_json(outp, spa_body)
                result.metadata_paths.append(str(outp))

            _save_json(meta_dir / "export_index.json", metadata)

            # IFW inventory
            ifw_docs: list[dict[str, Any]] = []
            ifw_path = meta_dir / "ifw_document_inventory.json"
            if ifw_path.is_file():
                try:
                    ifw_docs = _extract_ifw_docs(
                        json.loads(ifw_path.read_text(encoding="utf-8"))
                    )
                except Exception:
                    ifw_docs = []
            result.ifw_document_count = len(ifw_docs)
            if ifw_docs:
                summary = [
                    {
                        "documentIdentifier": d.get("documentIdentifier"),
                        "documentCode": d.get("documentCode"),
                        "documentDescription": d.get("documentDescription"),
                        "officialDate": d.get("officialDate"),
                        "mimeTypeBag": d.get("mimeTypeBag"),
                        "pageTotalQuantity": d.get("pageTotalQuantity"),
                    }
                    for d in ifw_docs
                ]
                outp = meta_dir / "ifw_document_summary.json"
                _save_json(outp, {"count": len(summary), "documents": summary})
                result.metadata_paths.append(str(outp))

            # UI eGrant / PDF downloads
            _click_download_controls(page)
            page.wait_for_timeout(4000)

            # ODP public download of IFW docs (uses identifiers from PC inventory).
            # Only attempt PDF variants; DOCX/XML-only entries are skipped.
            if download_ifw_via_odp and ifw_docs and _odp_api_key():
                limit = max(0, int(max_ifw_downloads))
                for doc in ifw_docs[:limit]:
                    doc_id = str(doc.get("documentIdentifier") or "").strip()
                    code = _safe_name(str(doc.get("documentCode") or "DOC"))
                    if not doc_id:
                        continue
                    mimes = doc.get("mimeTypeBag") or []
                    if isinstance(mimes, list) and mimes:
                        mime_upper = {str(m).upper() for m in mimes}
                        if "PDF" not in mime_upper:
                            continue
                    dest_file = files_dir / f"{code}_{_safe_name(doc_id)}.pdf"
                    if dest_file.exists() and dest_file.stat().st_size > 0:
                        continue
                    if _download_via_odp(app, doc_id, dest_file):
                        result.odp_downloads += 1
                        result.files.append(str(dest_file))
                    else:
                        result.errors.append(f"odp_download_failed:{doc_id}")

            # eGrant metadata-driven binary candidates (usually covered by UI click)
            egrant_docs: list[Mapping[str, Any]] = []
            for name in ("egrant_metadata", "public_egrant_metadata"):
                p = meta_dir / f"{name}.json"
                if not p.is_file():
                    continue
                try:
                    payload = json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if isinstance(payload, list):
                    egrant_docs.extend(
                        [d for d in payload if isinstance(d, Mapping)]
                    )
                elif isinstance(payload, Mapping):
                    bag = payload.get("documentBag") or []
                    if isinstance(bag, list):
                        egrant_docs.extend(
                            [d for d in bag if isinstance(d, Mapping)]
                        )
            for doc in egrant_docs:
                doc_id = str(doc.get("documentIdentifier") or "").strip()
                code = str(doc.get("documentCode") or "EGRANT")
                if not doc_id:
                    continue
                dest_file = files_dir / _safe_name(f"{code}_{doc_id}.pdf")
                if dest_file.exists():
                    continue
                # Prefer ODP for the published eGrant PDF when available
                if _odp_api_key() and _download_via_odp(app, doc_id, dest_file):
                    result.odp_downloads += 1
                    result.files.append(str(dest_file))

            # Collect downloads + dedupe
            result.files.extend(downloads)
            for path in files_dir.iterdir():
                if path.is_file() and str(path) not in result.files:
                    result.files.append(str(path))
            result.files = _dedupe_files_dir(files_dir)

            # Seal package
            package_files = list(files_dir.glob("*")) + list(meta_dir.glob("*.json"))
            if package_files:
                flat = dest / "package"
                if flat.exists():
                    shutil.rmtree(flat)
                flat.mkdir(exist_ok=True)
                for src in files_dir.glob("*"):
                    if src.is_file():
                        shutil.copy2(src, flat / src.name)
                for src in meta_dir.glob("*.json"):
                    shutil.copy2(src, flat / src.name)
                sealed = False
                last_exc: Exception | None = None
                for classification in (
                    "restricted_export_review",
                    "confidential_application",
                    "public_official",
                ):
                    try:
                        write_export_package_sidecar(
                            flat,
                            application_number=app,
                            tenant_id=tenant_id,
                            authorizing_user=authorizing_user,
                            classification=classification,
                        )
                        sealed = True
                        break
                    except Exception as exc:  # noqa: BLE001
                        last_exc = exc
                        continue
                if not sealed and last_exc is not None:
                    result.errors.append(
                        f"seal_failed:{type(last_exc).__name__}:{last_exc}"
                    )

            result.ok = bool(result.metadata_paths or result.files)
            if result.ok:
                result.message = "export_complete"
            else:
                result.message = "export_incomplete_no_metadata_or_files"

            context.storage_state(path=str(storage))
            # Write machine receipt (no tokens)
            receipt_path = dest / "export_receipt.json"
            _save_json(receipt_path, result.to_dict())
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
    "PatentCenterExportResult",
    "export_application_via_patent_center",
]
