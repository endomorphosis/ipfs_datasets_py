"""
Helpers for consumer Google Takeout URL generation and light-touch automation.

Google documents a customizable Takeout URL surface for selecting products,
delivery destination, and scheduled export frequency. This module uses that
documented entry point and keeps any browser automation explicitly
best-effort/experimental.
"""

from __future__ import annotations

import json
import re
import tempfile
import time
from html import unescape
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from .google_drive_oauth import resolve_drive_oauth_access_token

TAKEOUT_BASE_URL = "https://takeout.google.com/settings/takeout/custom"
DEFAULT_DESTINATION = "drive"
DEFAULT_FREQUENCY = "one_time"
SUPPORTED_DESTINATIONS = {"box", "dropbox", "drive", "email", "onedrive"}
SUPPORTED_FREQUENCIES = {"one_time", "2_months"}
_DATA_ID_RE = re.compile(r'data-id="([^"]+)"')
DRIVE_API_FILES_URL = "https://www.googleapis.com/drive/v3/files"
URL_RE = re.compile(r"https?://[^\s<>\"]+")


def extract_urls_from_text(text: str) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for match in URL_RE.findall(unescape(str(text or ""))):
        value = match.rstrip(").,;>'\"")
        if value and value not in seen:
            seen.add(value)
            urls.append(value)
    return urls


def _score_takeout_url(url: str) -> int:
    lowered = str(url or "").lower()
    score = 0
    if "takeout.google.com" in lowered:
        score += 10
    if "download" in lowered:
        score += 5
    if "takeout" in lowered:
        score += 4
    if "googleusercontent.com" in lowered or "storage.googleapis.com" in lowered:
        score += 3
    if "accounts.google.com" in lowered:
        score += 2
    return score


def extract_takeout_download_candidates_from_email(email_payload: dict[str, Any]) -> list[str]:
    candidate_text = "\n".join(
        [
            str(email_payload.get("subject") or ""),
            str(email_payload.get("body_text") or ""),
            str(email_payload.get("body_html") or ""),
        ]
    )
    urls = extract_urls_from_text(candidate_text)
    scored = sorted(urls, key=lambda value: (-_score_takeout_url(value), value))
    return [item for item in scored if _score_takeout_url(item) > 0]


def classify_takeout_email_stage(email_payload: dict[str, Any]) -> str:
    haystack = "\n".join(
        [
            str(email_payload.get("subject") or ""),
            str(email_payload.get("body_text") or ""),
            str(email_payload.get("body_html") or ""),
        ]
    ).lower()
    if "ready to download" in haystack or "download your files" in haystack or "your archive is ready" in haystack:
        return "archive_ready"
    if "archive of google data requested" in haystack or "request to create an archive" in haystack:
        return "archive_requested"
    if "takeout" in haystack or "archive of google data" in haystack:
        return "takeout_related"
    return "unknown"


async def poll_email_for_takeout_link(
    *,
    server: str,
    username: str,
    password: str,
    folder: str = "INBOX",
    port: int | None = None,
    use_ssl: bool = True,
    timeout: int = 30,
    limit: int = 25,
    search_criteria: str | None = None,
    from_contains: str = "google",
    subject_contains: str = "takeout",
    account_hint: str | None = None,
) -> dict[str, Any]:
    from .email_processor import EmailProcessor

    effective_search = str(search_criteria or "").strip()
    if not effective_search or effective_search.upper() == "ALL":
        search_parts: list[str] = []
        if subject_contains:
            escaped = str(subject_contains).replace('"', "")
            if escaped:
                search_parts.append(f'SUBJECT "{escaped}"')
        if from_contains:
            escaped = str(from_contains).replace('"', "")
            if escaped:
                search_parts.append(f'FROM "{escaped}"')
        effective_search = " ".join(search_parts) if search_parts else "ALL"

    processor = EmailProcessor(
        protocol="imap",
        server=server,
        port=port,
        username=username,
        password=password,
        use_ssl=use_ssl,
        timeout=timeout,
    )
    try:
        await processor.connect()
        result = await processor.fetch_emails(
            folder=folder,
            limit=limit,
            search_criteria=effective_search,
            include_attachments=False,
        )
    finally:
        try:
            await processor.disconnect()
        except Exception:
            pass

    if result.get("status") != "success":
        return result

    matching_messages: list[dict[str, Any]] = []
    from_filter = str(from_contains or "").lower().strip()
    subject_filter = str(subject_contains or "").lower().strip()
    account_filter = str(account_hint or "").lower().strip()

    for item in list(result.get("emails") or []):
        from_value = str(item.get("from") or "")
        to_value = str(item.get("to") or "")
        subject_value = str(item.get("subject") or "")
        body_text = str(item.get("body_text") or "")
        body_html = str(item.get("body_html") or "")
        haystack = "\n".join([subject_value, body_text, body_html]).lower()

        if from_filter and from_filter not in from_value.lower():
            continue
        if subject_filter and subject_filter not in haystack:
            continue
        if account_filter and account_filter not in to_value.lower() and account_filter not in haystack:
            continue

        links = extract_takeout_download_candidates_from_email(item)
        stage = classify_takeout_email_stage(item)
        matching_messages.append(
            {
                "subject": subject_value,
                "from": from_value,
                "to": to_value,
                "date": item.get("date"),
                "message_id": item.get("message_id"),
                "message_id_header": item.get("message_id_header"),
                "stage": stage,
                "download_links": links,
                "best_download_link": links[0] if links else None,
            }
        )

    matching_messages.sort(key=lambda entry: str(entry.get("date") or ""), reverse=True)
    latest = matching_messages[0] if matching_messages else None
    stage_counts: dict[str, int] = {}
    for item in matching_messages:
        stage = str(item.get("stage") or "unknown")
        stage_counts[stage] = stage_counts.get(stage, 0) + 1
    return {
        "status": "success",
        "folder": folder,
        "search_criteria": effective_search,
        "email_count": len(list(result.get("emails") or [])),
        "matched_email_count": len(matching_messages),
        "stage_counts": stage_counts,
        "latest_match": latest,
        "matches": matching_messages,
    }


def extract_data_ids_from_html(html_text: str) -> list[str]:
    seen: set[str] = set()
    results: list[str] = []
    for match in _DATA_ID_RE.findall(str(html_text or "")):
        value = str(match or "").strip()
        if value and value not in seen:
            seen.add(value)
            results.append(value)
    return results


def suggest_google_voice_product_ids(data_ids: list[str]) -> list[str]:
    candidates = []
    for item in data_ids:
        lowered = item.lower()
        if "voice" in lowered or "sms" in lowered or "call" in lowered:
            candidates.append(item)
    return candidates


def load_takeout_page_source(source: str | Path) -> str:
    path = Path(source).expanduser().resolve()
    return path.read_text(encoding="utf-8", errors="replace")


def build_takeout_custom_url(
    *,
    product_ids: list[str],
    destination: str = DEFAULT_DESTINATION,
    frequency: str = DEFAULT_FREQUENCY,
) -> str:
    cleaned_products = [str(item).strip() for item in product_ids if str(item).strip()]
    if not cleaned_products:
        raise ValueError("At least one Takeout product id is required.")
    if destination not in SUPPORTED_DESTINATIONS:
        raise ValueError(
            f"Unsupported destination '{destination}'. Use one of: {sorted(SUPPORTED_DESTINATIONS)}."
        )
    if frequency not in SUPPORTED_FREQUENCIES:
        raise ValueError(
            f"Unsupported frequency '{frequency}'. Use one of: {sorted(SUPPORTED_FREQUENCIES)}."
        )
    params = []
    if destination != DEFAULT_DESTINATION:
        params.append(f"dest={destination}")
    elif destination == "drive":
        params.append("dest=drive")
    if frequency != DEFAULT_FREQUENCY:
        params.append(f"frequency={frequency}")
    query = f"?{'&'.join(params)}" if params else ""
    return f"{TAKEOUT_BASE_URL}/" + ",".join(cleaned_products) + query


def build_google_voice_takeout_plan(
    *,
    product_ids: list[str] | None = None,
    page_source_path: str | Path | None = None,
    destination: str = DEFAULT_DESTINATION,
    frequency: str = DEFAULT_FREQUENCY,
) -> dict[str, Any]:
    data_ids: list[str] = []
    suggested_ids: list[str] = []
    if page_source_path:
        html_text = load_takeout_page_source(page_source_path)
        data_ids = extract_data_ids_from_html(html_text)
        suggested_ids = suggest_google_voice_product_ids(data_ids)
    selected_ids = [str(item).strip() for item in (product_ids or []) if str(item).strip()]
    if not selected_ids:
        selected_ids = list(suggested_ids)
    url = build_takeout_custom_url(
        product_ids=selected_ids,
        destination=destination,
        frequency=frequency,
    )
    return {
        "status": "success",
        "product_ids": selected_ids,
        "candidate_voice_product_ids": suggested_ids,
        "all_detected_data_ids": data_ids,
        "destination": destination,
        "frequency": frequency,
        "takeout_url": url,
        "notes": [
            "This URL uses Google's documented Takeout UI parameter surface.",
            "Product ids come from the page's data-id attributes when page source is provided.",
            "Google Voice product ids can vary by account and rendered page state, so inspect before relying on them.",
        ],
    }


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def launch_takeout_in_browser(
    *,
    url: str,
    browser: str = "chromium",
    headed: bool = True,
    user_data_dir: str | Path | None = None,
    auto_submit: bool = False,
    save_storage_state: str | Path | None = None,
    timeout_ms: int = 30_000,
) -> dict[str, Any]:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - depends on optional runtime
        raise RuntimeError(
            "Playwright is required for browser automation. Install playwright and browser binaries first."
        ) from exc

    browser_name = str(browser or "chromium").strip().lower()
    if browser_name not in {"chromium", "firefox", "webkit"}:
        raise ValueError("browser must be one of: chromium, firefox, webkit")

    profile_dir = (
        Path(user_data_dir).expanduser().resolve()
        if user_data_dir
        else Path(tempfile.mkdtemp(prefix="takeout-playwright-profile-"))
    )
    profile_dir.mkdir(parents=True, exist_ok=True)

    button_attempts = [
        "button:has-text('Create export')",
        "button:has-text('Link accounts and create an export')",
    ]

    with sync_playwright() as playwright:
        browser_type = getattr(playwright, browser_name)
        context = browser_type.launch_persistent_context(
            str(profile_dir),
            headless=not headed,
        )
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_timeout(1500)
        submit_status = "not_requested"

        if auto_submit:
            submit_status = "not_found"
            for selector in button_attempts:
                try:
                    locator = page.locator(selector).first
                    if locator.is_visible(timeout=2500):
                        locator.click(timeout=2500)
                        submit_status = "clicked"
                        break
                except PlaywrightTimeoutError:
                    continue
                except Exception:
                    continue

        state_path = None
        if save_storage_state:
            state_path = Path(save_storage_state).expanduser().resolve()
            state_path.parent.mkdir(parents=True, exist_ok=True)
            context.storage_state(path=str(state_path))

        title = ""
        try:
            title = page.title()
        except Exception:
            title = ""

        context.close()

    return {
        "status": "success",
        "started_at": _utc_now_iso(),
        "url": url,
        "browser": browser_name,
        "headed": headed,
        "auto_submit": auto_submit,
        "submit_status": submit_status,
        "user_data_dir": str(profile_dir),
        "storage_state_path": str(state_path) if state_path else None,
        "page_title": title,
    }


def capture_takeout_page_source(
    *,
    url: str = "https://takeout.google.com/settings/takeout",
    browser: str = "chromium",
    headed: bool = True,
    user_data_dir: str | Path | None = None,
    output_path: str | Path | None = None,
    timeout_ms: int = 30_000,
) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - depends on optional runtime
        raise RuntimeError(
            "Playwright is required for browser automation. Install playwright and browser binaries first."
        ) from exc

    browser_name = str(browser or "chromium").strip().lower()
    if browser_name not in {"chromium", "firefox", "webkit"}:
        raise ValueError("browser must be one of: chromium, firefox, webkit")

    profile_dir = (
        Path(user_data_dir).expanduser().resolve()
        if user_data_dir
        else Path(tempfile.mkdtemp(prefix="takeout-playwright-profile-"))
    )
    profile_dir.mkdir(parents=True, exist_ok=True)
    page_source_path = (
        Path(output_path).expanduser().resolve()
        if output_path
        else Path(tempfile.mkdtemp(prefix="takeout-page-source-")).resolve() / "takeout_page.html"
    )
    page_source_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser_type = getattr(playwright, browser_name)
        context = browser_type.launch_persistent_context(
            str(profile_dir),
            headless=not headed,
        )
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_timeout(1500)
        html_text = page.content()
        title = ""
        try:
            title = page.title()
        except Exception:
            title = ""
        page_source_path.write_text(html_text, encoding="utf-8")
        context.close()

    data_ids = extract_data_ids_from_html(html_text)
    return {
        "status": "success",
        "captured_at": _utc_now_iso(),
        "url": url,
        "browser": browser_name,
        "headed": headed,
        "user_data_dir": str(profile_dir),
        "output_path": str(page_source_path),
        "page_title": title,
        "detected_data_id_count": len(data_ids),
        "candidate_voice_product_ids": suggest_google_voice_product_ids(data_ids),
    }


def open_takeout_and_capture_download(
    *,
    url: str,
    browser: str = "chromium",
    headed: bool = True,
    user_data_dir: str | Path | None = None,
    auto_submit: bool = False,
    save_storage_state: str | Path | None = None,
    timeout_ms: int = 30_000,
    download_timeout_ms: int = 300_000,
    downloads_dir: str | Path | None = None,
    archive_glob: str = "*.zip",
) -> dict[str, Any]:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - depends on optional runtime
        raise RuntimeError(
            "Playwright is required for browser automation. Install playwright and browser binaries first."
        ) from exc

    browser_name = str(browser or "chromium").strip().lower()
    if browser_name not in {"chromium", "firefox", "webkit"}:
        raise ValueError("browser must be one of: chromium, firefox, webkit")

    profile_dir = (
        Path(user_data_dir).expanduser().resolve()
        if user_data_dir
        else Path(tempfile.mkdtemp(prefix="takeout-playwright-profile-"))
    )
    profile_dir.mkdir(parents=True, exist_ok=True)
    download_root = (
        Path(downloads_dir).expanduser().resolve()
        if downloads_dir
        else Path(tempfile.mkdtemp(prefix="takeout-downloads-"))
    )
    download_root.mkdir(parents=True, exist_ok=True)

    result: dict[str, Any] = {
        "status": "success",
        "started_at": _utc_now_iso(),
        "url": url,
        "browser": browser_name,
        "headed": headed,
        "auto_submit": auto_submit,
        "user_data_dir": str(profile_dir),
        "downloads_dir": str(download_root),
        "archive_glob": archive_glob,
    }

    button_attempts = [
        "button:has-text('Create export')",
        "button:has-text('Link accounts and create an export')",
    ]

    with sync_playwright() as playwright:
        browser_type = getattr(playwright, browser_name)
        context = browser_type.launch_persistent_context(
            str(profile_dir),
            headless=not headed,
            accept_downloads=True,
            downloads_path=str(download_root),
        )
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_timeout(1500)

        submit_status = "not_requested"
        if auto_submit:
            submit_status = "not_found"
            for selector in button_attempts:
                try:
                    locator = page.locator(selector).first
                    if locator.is_visible(timeout=2500):
                        locator.click(timeout=2500)
                        submit_status = "clicked"
                        break
                except PlaywrightTimeoutError:
                    continue
                except Exception:
                    continue

        result["submit_status"] = submit_status

        state_path = None
        if save_storage_state:
            state_path = Path(save_storage_state).expanduser().resolve()
            state_path.parent.mkdir(parents=True, exist_ok=True)
            context.storage_state(path=str(state_path))
            result["storage_state_path"] = str(state_path)
        else:
            result["storage_state_path"] = None

        try:
            result["page_title"] = page.title()
        except Exception:
            result["page_title"] = ""

        deadline = time.monotonic() + (download_timeout_ms / 1000.0)
        download_path: Path | None = None
        suggested_filename = ""

        while time.monotonic() < deadline:
            try:
                with page.expect_download(timeout=2000) as pending_download:
                    page.wait_for_timeout(1000)
                download = pending_download.value
                suggested_filename = download.suggested_filename
                saved_path = download.path()
                if saved_path:
                    download_path = Path(saved_path).resolve()
                else:
                    destination = download_root / suggested_filename
                    download.save_as(str(destination))
                    download_path = destination.resolve()
                break
            except PlaywrightTimeoutError:
                existing = sorted(download_root.glob(archive_glob))
                if existing:
                    download_path = existing[-1].resolve()
                    suggested_filename = download_path.name
                    break
                continue

        context.close()

    if download_path is None or not download_path.exists():
        result["status"] = "pending"
        result["download_status"] = "not_captured"
        result["message"] = (
            "No archive download was captured within the timeout window. "
            "The export may still be processing in Google Takeout."
        )
        return result

    result["download_status"] = "captured"
    result["download_path"] = str(download_path)
    result["suggested_filename"] = suggested_filename or download_path.name
    result["download_size_bytes"] = download_path.stat().st_size
    return result


def poll_for_takeout_archive(
    *,
    downloads_dir: str | Path,
    archive_glob: str = "*.zip",
    timeout_ms: int = 300_000,
    poll_interval_ms: int = 2_000,
) -> dict[str, Any]:
    download_root = Path(downloads_dir).expanduser().resolve()
    download_root.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    best_match: Path | None = None

    while time.monotonic() < deadline:
        matches = sorted(download_root.glob(archive_glob))
        complete_matches = [path for path in matches if path.is_file() and not path.name.endswith(".crdownload")]
        if complete_matches:
            best_match = complete_matches[-1].resolve()
            break
        time.sleep(max(0.1, poll_interval_ms / 1000.0))

    if best_match is None:
        return {
            "status": "pending",
            "downloads_dir": str(download_root),
            "archive_glob": archive_glob,
            "message": "No completed Takeout archive found in the download directory before timeout.",
        }

    return {
        "status": "success",
        "downloads_dir": str(download_root),
        "archive_glob": archive_glob,
        "download_path": str(best_match),
        "download_size_bytes": best_match.stat().st_size,
    }


def list_drive_takeout_candidates(
    *,
    access_token: str,
    name_contains: str = "takeout",
    include_folders: bool = True,
    modified_after: str | None = None,
    page_size: int = 25,
) -> list[dict[str, Any]]:
    name_value = str(name_contains or "takeout").replace("'", "\\'")
    query_parts = [f"name contains '{name_value}'", "trashed = false"]
    if not include_folders:
        query_parts.append("mimeType != 'application/vnd.google-apps.folder'")
    if modified_after:
        normalized = str(modified_after).replace("Z", "+00:00")
        try:
            iso_value = datetime.fromisoformat(normalized).astimezone(UTC).replace(microsecond=0).isoformat()
            query_parts.append(f"modifiedTime > '{iso_value}'")
        except Exception:
            pass
    response = requests.get(
        DRIVE_API_FILES_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        params={
            "q": " and ".join(query_parts),
            "fields": "files(id,name,mimeType,modifiedTime,size,parents)",
            "pageSize": page_size,
            "orderBy": "modifiedTime desc",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = dict(response.json())
    return list(payload.get("files") or [])


def list_drive_folder_children(
    *,
    access_token: str,
    folder_id: str,
    page_size: int = 100,
) -> list[dict[str, Any]]:
    response = requests.get(
        DRIVE_API_FILES_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        params={
            "q": f"'{folder_id}' in parents and trashed = false",
            "fields": "files(id,name,mimeType,modifiedTime,size,parents)",
            "pageSize": page_size,
            "orderBy": "modifiedTime desc",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = dict(response.json())
    return list(payload.get("files") or [])


def _find_downloadable_descendant(
    *,
    access_token: str,
    folder_id: str,
    max_depth: int = 4,
) -> dict[str, Any] | None:
    if max_depth < 0:
        return None
    children = list_drive_folder_children(access_token=access_token, folder_id=folder_id)
    files = [
        item for item in children
        if str(item.get("mimeType") or "") != "application/vnd.google-apps.folder"
    ]
    if files:
        return files[0]
    if max_depth == 0:
        return None
    folders = [
        item for item in children
        if str(item.get("mimeType") or "") == "application/vnd.google-apps.folder"
    ]
    for folder in folders:
        descendant = _find_downloadable_descendant(
            access_token=access_token,
            folder_id=str(folder.get("id") or ""),
            max_depth=max_depth - 1,
        )
        if descendant is not None:
            return descendant
    return None


def poll_drive_for_takeout_artifact(
    *,
    client_secrets_path: str,
    account_hint: str,
    token_cache_path: str | Path | None = None,
    open_browser: bool = True,
    name_contains: str = "takeout",
    include_folders: bool = True,
    modified_after: str | None = None,
    timeout_ms: int = 300_000,
    poll_interval_ms: int = 5_000,
) -> dict[str, Any]:
    access_token, token_payload = resolve_drive_oauth_access_token(
        account_hint=account_hint,
        client_secrets_path=client_secrets_path,
        token_cache_path=token_cache_path,
        open_browser=open_browser,
    )
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    best_match: dict[str, Any] | None = None

    while time.monotonic() < deadline:
        matches = list_drive_takeout_candidates(
            access_token=access_token,
            name_contains=name_contains,
            include_folders=include_folders,
            modified_after=modified_after,
        )
        downloadable = [
            item for item in matches
            if str(item.get("mimeType") or "") != "application/vnd.google-apps.folder"
        ]
        if downloadable:
            best_match = downloadable[0]
            break
        if include_folders and matches:
            best_match = matches[0]
            break
        time.sleep(max(0.1, poll_interval_ms / 1000.0))

    if best_match is None:
        return {
            "status": "pending",
            "name_contains": name_contains,
            "modified_after": modified_after,
            "message": "No matching Google Drive Takeout artifact appeared before timeout.",
            "token_cache_path": str(Path(token_cache_path).expanduser().resolve()) if token_cache_path else None,
        }

    return {
        "status": "success",
        "name_contains": name_contains,
        "modified_after": modified_after,
        "artifact": best_match,
        "token_cache_path": str(Path(token_cache_path).expanduser().resolve()) if token_cache_path else None,
        "has_refresh_token": bool(token_payload.get("refresh_token")),
    }


def download_drive_file(
    *,
    access_token: str,
    file_id: str,
    output_path: str | Path,
) -> dict[str, Any]:
    destination = Path(output_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    response = requests.get(
        f"{DRIVE_API_FILES_URL}/{file_id}",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"alt": "media"},
        stream=True,
        timeout=60,
    )
    response.raise_for_status()
    with destination.open("wb") as handle:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if chunk:
                handle.write(chunk)
    return {
        "status": "success",
        "file_id": file_id,
        "output_path": str(destination),
        "size_bytes": destination.stat().st_size,
    }


def poll_drive_and_optionally_download(
    *,
    client_secrets_path: str,
    account_hint: str,
    token_cache_path: str | Path | None = None,
    open_browser: bool = True,
    name_contains: str = "takeout",
    modified_after: str | None = None,
    timeout_ms: int = 300_000,
    poll_interval_ms: int = 5_000,
    download_dir: str | Path | None = None,
) -> dict[str, Any]:
    access_token, _token_payload = resolve_drive_oauth_access_token(
        account_hint=account_hint,
        client_secrets_path=client_secrets_path,
        token_cache_path=token_cache_path,
        open_browser=open_browser,
    )
    artifact_result = poll_drive_for_takeout_artifact(
        client_secrets_path=client_secrets_path,
        account_hint=account_hint,
        token_cache_path=token_cache_path,
        open_browser=open_browser,
        name_contains=name_contains,
        modified_after=modified_after,
        include_folders=True,
        timeout_ms=timeout_ms,
        poll_interval_ms=poll_interval_ms,
    )
    if artifact_result.get("status") != "success":
        return artifact_result

    artifact = dict(artifact_result.get("artifact") or {})
    mime_type = str(artifact.get("mimeType") or "")
    if mime_type == "application/vnd.google-apps.folder":
        descendant = _find_downloadable_descendant(
            access_token=access_token,
            folder_id=str(artifact.get("id") or ""),
            max_depth=4,
        )
        if descendant is None:
            artifact_result["download_status"] = "folder_only"
            artifact_result["message"] = (
                "Drive reported a folder artifact, but no downloadable file was found inside it yet."
            )
            return artifact_result
        artifact_result["folder_artifact"] = artifact
        artifact = dict(descendant)
        artifact_result["artifact"] = artifact

    if not download_dir:
        artifact_result["download_status"] = "skipped"
        return artifact_result

    filename = str(artifact.get("name") or f"{artifact.get('id', 'drive-file')}.zip")
    download_result = download_drive_file(
        access_token=access_token,
        file_id=str(artifact.get("id") or ""),
        output_path=Path(download_dir).expanduser().resolve() / filename,
    )
    artifact_result["download_status"] = "captured"
    artifact_result["download"] = download_result
    return artifact_result


def save_takeout_plan(payload: dict[str, Any], output_path: str | Path) -> None:
    path = Path(output_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
