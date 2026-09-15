#!/usr/bin/env python3
"""Syria: ARCHIVE-ONLY collector — parliament.gov.sy laws/decrees + jus.moj.gov.sy decree paths.

Live DNS for parliament.gov.sy / jus.moj.gov.sy is dead from this host.
Discover via Wayback CDX (prefer http://web.archive.org/cdx/...); fetch via
archive_fallbacks of those official URLs only.
No commercial Syria Report / NGO mirrors. No WAF bypass. Hub HOLD — no HF upload.
Not legal advice.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urlencode, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, existing_ids, html_to_text, log_failure, utcnow, write_summary
from world_lib import env_int, first_title, pdf_to_text, save_instrument, setup_log, slug_id
import archive_fallbacks as af

CC, COUNTRY, LANG = "sy", "Syria", "ar"
SOURCE_TYPE = "parliament_sy_archive"
LICENSE = (
    "Official Syrian legislation texts as published by the People's Assembly "
    "(parliament.gov.sy) and Ministry of Justice justice portal (jus.moj.gov.sy). "
    "Retrieved from Internet Archive snapshots of those official URLs only "
    "(live DNS unavailable from this collector host). Authentic official text "
    "prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=http://parliament.gov.sy/)"
ART = re.compile(r"(?im)^\s*((?:المادة|مادة)\s*\(?\s*[0-9\u0660-\u0669]+\s*\)?)")
OFFICIAL_HOSTS = ("parliament.gov.sy", "www.parliament.gov.sy", "jus.moj.gov.sy", "www.jus.moj.gov.sy")
CDX_HTTP = "http://web.archive.org/cdx/search/cdx"
log = logging.getLogger("sy")


def _norm_official(url: str) -> str | None:
    if not url:
        return None
    url = url.strip().replace("&amp;", "&").split("#")[0]
    if "http://" in url[8:]:
        url = url[: url.find("http://", 8)]
    if "https://" in url[9:]:
        url = url[: url.find("https://", 9)]
    url = url.replace(":80/", "/").replace(":80?", "?")
    try:
        p = urlparse(url)
    except Exception:
        return None
    host = (p.hostname or "").lower()
    if host not in OFFICIAL_HOSTS:
        return None
    scheme = p.scheme or "http"
    path = p.path or "/"
    query = f"?{p.query}" if p.query else ""
    return f"{scheme}://{host}{path}{query}"


def _is_instrument_url(url: str) -> bool:
    low = unquote(url).lower()
    host = (urlparse(url).hostname or "").lower()
    if host in ("parliament.gov.sy", "www.parliament.gov.sy"):
        if "/laws/" not in low:
            return False
        path = urlparse(url).path.lower()
        return path.endswith((".htm", ".html", ".pdf"))
    if host in ("jus.moj.gov.sy", "www.jus.moj.gov.sy"):
        if "/ar/decrees" in low or "/ar/constitution" in low:
            return True
        if "/sites/default/files/" in low and low.split("?")[0].endswith(".pdf"):
            u = unquote(url)
            keys = ("مرسوم", "قانون", "تشريع", "decree", "law", "دستور", "إعلان", "اعلان")
            return any((k.lower() in u.lower()) if k.isascii() else (k in u) for k in keys)
        return False
    return False


def _ident_from_url(url: str) -> str:
    p = urlparse(url)
    path = unquote(p.path or "")
    host = (p.hostname or "").lower().replace("www.", "")
    if "parliament.gov.sy" in host:
        m = re.search(r"/laws/(Decree|Law|Laws)/(\d{4})/([^/?#]+)$", path, re.I)
        if m:
            kind, year, stem = m.group(1).lower(), m.group(2), Path(m.group(3)).stem
            stem = re.sub(r"[^\w.\-]+", "-", stem).strip("-")[:100]
            return f"{kind}-{year}-{stem}"[:160]
        stem = re.sub(r"[^\w.\-]+", "-", Path(path).stem).strip("-")[:120]
        return f"parliament-{stem}"[:160]
    if "/ar/constitution" in path.lower():
        return "moj-constitution"
    if "/ar/decrees" in path.lower():
        page = ""
        qm = re.search(r"[?&]page=(\d+)", url)
        if qm:
            page = f"-p{qm.group(1)}"
        return f"moj-decrees{page}"[:160]
    if path.lower().endswith(".pdf"):
        stem = Path(unquote(path)).stem
        stem = re.sub(r"[^\w.\-\u0600-\u06FF]+", "-", stem).strip("-")[:100]
        return f"moj-pdf-{stem or 'file'}"[:160]
    stem = re.sub(r"[^\w.\-]+", "-", path.strip("/")).strip("-")[:120]
    return f"moj-{stem or 'page'}"[:160]


def _decode_html(body: bytes) -> str:
    if not body:
        return ""
    head = body[:2000].lower()
    encs: list[str] = []
    if b"windows-1256" in head or b"cp1256" in head:
        encs.append("windows-1256")
    if b"charset=utf-8" in head or b'charset="utf-8"' in head:
        encs.append("utf-8")
    encs.extend(["windows-1256", "utf-8", "cp1256", "latin-1"])
    seen: set[str] = set()
    for enc in encs:
        if enc in seen:
            continue
        seen.add(enc)
        try:
            return body.decode(enc)
        except Exception:
            continue
    return body.decode("utf-8", "replace")


def http_cdx(url_prefix: str, *, limit: int = 400) -> list[dict]:
    """Prefer plain HTTP Wayback CDX (HTTPS often SSLEOF from this host)."""
    params = {
        "url": url_prefix,
        "output": "json",
        "fl": "urlkey,timestamp,original,mimetype,statuscode,digest,length",
        "limit": str(min(limit, 500)),
        "collapse": "urlkey",
        "matchType": "prefix",
        "filter": "statuscode:200",
    }
    qs = urlencode(params)
    target = f"{CDX_HTTP}?{qs}"
    out: list[dict] = []
    # 1) curl HTTP (most reliable from this host)
    for attempt in range(1, 4):
        try:
            proc = subprocess.run(
                ["curl", "-fsSL", "--max-time", "90", "-A", UA, target],
                check=False,
                capture_output=True,
                timeout=100,
            )
            if proc.returncode == 0 and proc.stdout:
                data = json.loads(proc.stdout.decode("utf-8", "replace"))
                if isinstance(data, list) and data:
                    headers = data[0]
                    for row in data[1:]:
                        if not isinstance(row, list) or len(row) < len(headers):
                            continue
                        rec = dict(zip(headers, row))
                        out.append(rec)
                    log.info("http_cdx curl %s hits=%s", url_prefix, len(out))
                    return out[:limit]
            log.info("http_cdx curl fail %s rc=%s attempt=%s", url_prefix, proc.returncode, attempt)
        except Exception as exc:
            log.info("http_cdx curl err %s: %s", url_prefix, exc)
        time.sleep(1.5 * attempt)
    # 2) requests HTTP, no HTTPS redirect follow
    try:
        import requests

        r = requests.get(
            CDX_HTTP,
            params=params,
            timeout=(20, 90),
            allow_redirects=False,
            headers={"User-Agent": UA},
        )
        if r.status_code == 200 and r.content:
            data = r.json()
            if isinstance(data, list) and data:
                headers = data[0]
                for row in data[1:]:
                    if not isinstance(row, list) or len(row) < len(headers):
                        continue
                    out.append(dict(zip(headers, row)))
                log.info("http_cdx requests %s hits=%s", url_prefix, len(out))
                return out[:limit]
    except Exception as exc:
        log.info("http_cdx requests err %s: %s", url_prefix, exc)
    # 3) archive_fallbacks helper (may hit HTTPS)
    try:
        hits = af.search_wayback_machine(url_prefix, limit=limit, match_type="prefix", collapse="urlkey")
        log.info("http_cdx af fallback %s hits=%s", url_prefix, len(hits or []))
        return hits or []
    except Exception as exc:
        log.info("http_cdx af err %s: %s", url_prefix, exc)
        return []



def _curl_wayback(url: str, ts: str | None = None) -> dict:
    """HTTP Wayback id_ replay via curl (requests HTTPS often SSLEOF here)."""
    out = {"status": "error", "content": b"", "text": "", "error": "", "wayback_url": "", "capture_timestamp": ts or ""}
    stamp = ts or "2"
    wb = f"http://web.archive.org/web/{stamp}id_/{url}"
    try:
        proc = subprocess.run(["curl", "-fsSL", "--max-time", "90", "-A", UA, wb], check=False, capture_output=True, timeout=100)
    except Exception as exc:
        out["error"] = f"curl:{exc}"
        return out
    if proc.returncode != 0 or not proc.stdout:
        err = (proc.stderr or b"")[:200].decode("utf-8", "replace")
        out["error"] = f"curl_rc_{proc.returncode}:{err}"
        return out
    out.update(status="success", content=proc.stdout, wayback_url=wb, capture_timestamp=ts or stamp)
    return out


def fetch_archive(url: str, ts: str | None = None, *, min_text: int = 80) -> dict:
    """ARCHIVE-ONLY fetch: Wayback replay of official URL (no live DNS)."""
    out = {"status": "error", "text": "", "content": b"", "method": "", "error": "", "source_url": url}
    w = _curl_wayback(url, ts)
    if w.get("status") != "success":
        try:
            w2 = af.get_wayback_content(url, timestamp=ts or None)
        except Exception as exc:
            out["error"] = f"wayback:{w.get('error')};af:{exc}"
            return out
        if w2.get("status") != "success":
            out["error"] = f"wayback:{w.get('error')};af:{w2.get('error')}"
            return out
        w = w2
    body = w.get("content") or b""
    ctype = (w.get("content_type") or "").lower()
    text = ""
    if (isinstance(body, bytes) and body[:4] == b"%PDF") or "pdf" in ctype:
        pdf_bytes = body if isinstance(body, bytes) else b""
        text = pdf_to_text(pdf_bytes) if pdf_bytes[:4] == b"%PDF" else ""
        method = "wayback_pdf"
    else:
        raw = _decode_html(body if isinstance(body, bytes) else b"")
        text = html_to_text(raw) if "<" in raw[:500] else raw
        method = "wayback_html"
    if len(text) < min_text:
        out["error"] = f"short:{len(text)}"
        out["method"] = method
        return out
    if af.is_challenge(text, 200):
        out["error"] = "challenge_or_shell"
        return out
    out.update(
        status="success",
        text=text,
        content=body if isinstance(body, bytes) else text.encode("utf-8", "replace"),
        method=method,
        source_url=w.get("wayback_url") or url,
        capture_timestamp=w.get("capture_timestamp") or ts or "",
    )
    return out


def _load_catalog(seen_url: set[str], seen_id: set[str]) -> list[tuple[str, str, str, dict]]:
    items: list[tuple[str, str, str, dict]] = []
    cat = ROOT / CC / "raw" / "catalog.jsonl"
    if not cat.exists():
        return items
    for line in cat.open(encoding="utf-8"):
        try:
            row = json.loads(line)
        except Exception:
            continue
        url = _norm_official(row.get("url") or row.get("source_url") or "")
        if not url or not _is_instrument_url(url):
            continue
        canon = url.replace("://www.parliament.gov.sy", "://parliament.gov.sy")
        canon = canon.replace("://www.jus.moj.gov.sy", "://jus.moj.gov.sy")
        if canon in seen_url:
            continue
        ident = row.get("ident") or _ident_from_url(canon)
        if ident in seen_id:
            continue
        seen_url.add(canon)
        seen_id.add(ident)
        items.append(
            (
                ident,
                canon,
                row.get("title") or ident,
                {"cdx_ts": row.get("cdx_ts"), "portal": row.get("portal") or "parliament", "from": "catalog"},
            )
        )
    log.info("loaded prior catalog %s", len(items))
    return items


def discover() -> list[tuple[str, str, str, dict]]:
    items: list[tuple[str, str, str, dict]] = []
    seen_url: set[str] = set()
    seen_id: set[str] = set()
    limit = env_int("CDX_LIMIT", 500)

    prefixes = [
        "parliament.gov.sy/laws/",
        "www.parliament.gov.sy/laws/",
        "parliament.gov.sy/laws/Decree/",
        "parliament.gov.sy/laws/Law/",
        "jus.moj.gov.sy/ar/decrees",
        "jus.moj.gov.sy/ar/constitution",
        "jus.moj.gov.sy/sites/default/files/",
    ]
    for prefix in prefixes:
        for hit in http_cdx(prefix, limit=limit):
            orig = (hit.get("original") or "").strip()
            url = _norm_official(orig)
            if not url or not _is_instrument_url(url):
                continue
            canon = url.replace("://www.parliament.gov.sy", "://parliament.gov.sy")
            canon = canon.replace("://www.jus.moj.gov.sy", "://jus.moj.gov.sy")
            if canon in seen_url:
                continue
            path = urlparse(canon).path.lower()
            if path.endswith((".tif", ".tiff", ".gif", ".jpg", ".jpeg", ".png", ".js", ".css")):
                continue
            mime = (hit.get("mimetype") or "").lower()
            if mime and not any(x in mime for x in ("html", "pdf", "text", "octet")):
                # keep unknown; drop images
                if mime.startswith("image/"):
                    continue
            ident = _ident_from_url(canon)
            if ident in seen_id:
                continue
            seen_url.add(canon)
            seen_id.add(ident)
            title_hint = Path(unquote(urlparse(canon).path)).stem.replace("_", " ").replace("-", " ")
            items.append(
                (
                    ident,
                    canon,
                    title_hint[:240] or ident,
                    {
                        "cdx_ts": hit.get("timestamp"),
                        "mimetype": hit.get("mimetype"),
                        "portal": "parliament" if "parliament.gov.sy" in canon else "jus_moj",
                    },
                )
            )
        time.sleep(0.35)

    if not items:
        items = _load_catalog(seen_url, seen_id)

    items.sort(key=lambda x: (0 if x[3].get("portal") == "parliament" else 1, x[0]))

    cat = ROOT / CC / "raw" / "catalog.jsonl"
    cat.parent.mkdir(parents=True, exist_ok=True)
    with cat.open("w", encoding="utf-8") as f:
        for ident, url, title, meta in items:
            f.write(
                json.dumps(
                    {
                        "ident": ident,
                        "url": url,
                        "title": title,
                        "cdx_ts": (meta or {}).get("cdx_ts"),
                        "portal": (meta or {}).get("portal"),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    log.info("cdx catalog=%s (ARCHIVE-ONLY; live DNS dead)", len(items))
    return items


def main():
    setup_log(CC)
    log.info("START ARCHIVE-ONLY Syria collector; DNS dead — CDX + Wayback only")
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 60)
    max_seconds = env_int("MAX_SECONDS", 3600)
    t_start = time.time()
    done = existing_ids(CC)
    catalog = discover()
    ok = skip = fail = 0
    methods: dict[str, int] = {}
    portals: dict[str, int] = {}

    for ident, url, title_hint, meta in catalog:
        if max_new and ok >= max_new:
            break
        if max_seconds and (time.time() - t_start) > max_seconds:
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        got = fetch_archive(url, (meta or {}).get("cdx_ts"), min_text=80)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(
                CC,
                {
                    "identifier": ident,
                    "source_url": url,
                    "reason": got.get("error"),
                    "portal": (meta or {}).get("portal"),
                },
            )
            time.sleep(0.35)
            continue
        title = first_title(text, title_hint or ident)
        year = None
        ym = re.search(r"(19\d{2}|20\d{2})", ident) or re.search(r"(19\d{2}|20\d{2})", title)
        if ym:
            year = f"{ym.group(1)}-01-01"
        method = got.get("method") or "wayback"
        portal = (meta or {}).get("portal") or "unknown"
        if save_instrument(
            cc=CC,
            country=COUNTRY,
            language=LANG,
            ident=ident,
            title=title,
            text=text,
            source_url=url,
            source_type=SOURCE_TYPE,
            license_text=LICENSE,
            collector="collect_sy.py",
            date=year,
            article_re=ART,
            extra_meta={
                "fetch_method": method,
                "portal": portal,
                "retrieval": "archive",
                "archive_only": True,
                "dns_live": False,
                "cdx_ts": (meta or {}).get("cdx_ts"),
                "wayback_url": got.get("source_url"),
            },
        ):
            ok += 1
            done.add(rid)
            methods[method] = methods.get(method, 0) + 1
            portals[portal] = portals.get(portal, 0) + 1
            log.info("ok %s chars=%s method=%s portal=%s", ident, len(text), method, portal)
        else:
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "save_failed"})
        time.sleep(0.4)

    write_summary(
        CC,
        country=COUNTRY,
        source="Syria People's Assembly laws/decrees + MoJ jus decree paths (ARCHIVE-ONLY)",
        source_urls=[
            "http://parliament.gov.sy/laws/",
            "http://parliament.gov.sy/laws/Decree/",
            "http://jus.moj.gov.sy/ar/decrees",
            "http://jus.moj.gov.sy/ar/constitution",
        ],
        license_text=LICENSE,
        discovered=len(catalog),
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage="Wayback CDX HTML/PDF under parliament.gov.sy/laws/ + jus.moj.gov.sy decree/constitution paths; incomplete",
        notes=(
            "ARCHIVE-ONLY / DNS dead from this host. Discovery via Wayback CDX "
            "(http://web.archive.org/cdx/...) of official parliament.gov.sy and "
            "jus.moj.gov.sy URLs only; fetch via archive_fallbacks (no live fetch, "
            "no commercial/NGO mirrors, no WAF bypass, Hub HOLD). "
            f"portals={portals} methods={methods}. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s discovered=%s ARCHIVE-ONLY", ok, skip, fail, len(catalog))


if __name__ == "__main__":
    main()
