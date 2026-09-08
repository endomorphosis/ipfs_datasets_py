#!/usr/bin/env python3
"""Zimbabwe: Parliament of Zimbabwe official Act PDFs (parlzim.gov.zw).

Primary catalog: historic acts-list/download/ PDFs (official Parliament statute
book) + live FileBird Acts folder + wp-content Act uploads + attachments/*_ACT_*.pdf.
Live official URL first; Wayback of the same official URL on failure (CDX
timestamped replay — /web/2id_/ alone often 404s for historic acts-list).
Skips ZimLII / Veritas / commercial consolidators. Acts-only (SI out of scope).
"""
from __future__ import annotations
import logging, re, sys, time
from pathlib import Path
from urllib.parse import unquote, urljoin
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import (
    cdx_urls,
    env_int,
    fetch_official_prefer_pdf,
    live_get,
    save_instrument,
    setup_log,
    slug_id,
)

CC, COUNTRY, LANG = "zw", "Zimbabwe", "en"
SOURCE_TYPE = "parliament_zimbabwe"
LICENSE = (
    "Parliament of Zimbabwe (parlzim.gov.zw) official Acts / statute PDFs. "
    "Authentic text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.parlzim.gov.zw/)"
ART = re.compile(r"(?im)^\s*((?:Section|Sec\.)\s+\d+[A-Za-z]?\.?|\d+[A-Za-z]?(?=\s{2,}[A-Za-z]))")
log = logging.getLogger("zw")

ACTISH = re.compile(
    r"(_ACT_|\bACT\b|Act[-_]|Constitution|Amendment[-_]?Act)",
    re.I,
)
SKIP = re.compile(
    r"(statutory.?instrument|\bSI[_\-\s]?\d|hansard|budget.?office|digest|analys[ei]s|hearing|vacancy|advert|newsletter|"
    r"auditor|committee.?report|nomination|fact[_\-\s]?sheet|policy.?option|"
    r"audit.?report|call.?for.?public|public.?hearing|thematic.?committee|"
    r"leader.?of.?gover|ministers.?obligation|discussion.?paper|laymans.?draft|"
    r"bill.?tracker|control.?list|empower.?bank|value.?for.?money|wetland|"
    r"gbv.?crisis|measures.?anaysis|clerk.?s.?blog)",
    re.I,
)
LAW_MARK = re.compile(
    r"(AN ACT\b|Chapter\s+\d+\s*:\s*\d+|ASSOCIATION ACT|ACT\s*\[Chapter|"
    r"Short title|This Act may be cited|CONSTITUTION OF ZIMBABWE)",
    re.I,
)

# FileBird "Acts" folder on parlzim.gov.zw/acts/ (encrypted folder id from page JSON)
FILEBIRD_ACTS_FOLDER = "h11Dr15mUOZERSIC71U/zg=="


def _norm(url: str) -> str:
    u = (url or "").split("#")[0].split("?")[0]
    u = u.replace("http://", "https://").replace(":80/", "/")
    u = re.sub(r"https://parlzim\.gov\.zw/", "https://www.parlzim.gov.zw/", u)
    u = re.sub(r"https://justice\.gov\.zw/", "https://www.justice.gov.zw/", u)
    return u


def _ident_from_url(url: str) -> str:
    path = unquote(url.split("?")[0].rstrip("/"))
    name = Path(path).name
    if name.lower().endswith(".pdf"):
        stem = name[:-4]
    elif "/download/" in path:
        stem = name  # opaque id like 1000_b53f...
    else:
        stem = name
    stem = re.sub(r"\s+", " ", stem).strip()
    return re.sub(r"[^\w.\-]+", "-", stem)[:160] or "zw-doc"


def _is_law_url(url: str) -> bool:
    u = url or ""
    low = u.lower()
    if "zimlii.org" in low or "veritaszim" in low or "gazettes.africa" in low:
        return False
    if "parlzim.gov.zw" not in low:
        return False  # parlzim only
    if SKIP.search(u):
        return False
    # Official Parliament acts-list downloads (opaque ids, no .pdf suffix)
    if "parlzim.gov.zw" in low and "/acts-list/download/" in low:
        return True
    if ".pdf" not in low:
        return False
    name = unquote(u.split("/")[-1])
    if SKIP.search(name):
        return False
    if "parlzim.gov.zw" in low:
        if "/attachments/" in low and ACTISH.search(name):
            return True
        if "/wp-content/uploads/" in low and ACTISH.search(name):
            return True
        if ACTISH.search(name):
            return True
    if "justice.gov.zw" in low and ACTISH.search(name):
        if re.search(r"(Act|Constitution)", name, re.I):
            return True
    return False


def _title_from_text(text: str, fallback: str) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    for ln in lines[:40]:
        if re.search(r"\bACT\b", ln) and 8 <= len(ln) <= 120 and not ln.lower().startswith("chapter"):
            if not re.match(r"^(TITLE|PREVIOUS|NEXT)\b", ln, re.I):
                return ln[:240]
    for ln in lines[:40]:
        if re.search(r"Constitution of Zimbabwe", ln, re.I) and len(ln) >= 12:
            return ln[:240]
    for ln in lines:
        if len(ln) >= 12 and not ln.lower().startswith("just a moment"):
            return ln[:240]
    return fallback[:240]


def _media_api_pdfs() -> list[tuple[str, str]]:
    """WP media library: browse all pages + search=Act for named Act PDFs."""
    items, seen = [], set()
    try:
        import requests
        from requests.packages.urllib3.exceptions import InsecureRequestWarning
        requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
    except Exception:
        return items

    def _ingest(data):
        for it in data or []:
            url = _norm(it.get("source_url") or "")
            mime = (it.get("mime_type") or "").lower()
            if "pdf" not in mime and not url.lower().endswith(".pdf"):
                continue
            if not _is_law_url(url) or url in seen:
                continue
            seen.add(url)
            items.append((_ident_from_url(url), url))

    # Full media crawl
    page = 1
    while page <= 40:
        try:
            r = requests.get(
                "https://www.parlzim.gov.zw/wp-json/wp/v2/media",
                params={"per_page": 100, "page": page},
                headers={"User-Agent": UA},
                timeout=60,
                verify=False,
            )
        except Exception as exc:
            log.info("media api fail page=%s: %s", page, exc)
            break
        if r.status_code != 200:
            break
        data = r.json() or []
        if not data:
            break
        _ingest(data)
        total = r.headers.get("X-WP-TotalPages") or r.headers.get("x-wp-totalpages")
        if total and page >= int(total):
            break
        if len(data) < 100:
            break
        page += 1

    # Targeted search (catches Act PDFs buried past early pages)
    for page in range(1, 6):
        try:
            r = requests.get(
                "https://www.parlzim.gov.zw/wp-json/wp/v2/media",
                params={"per_page": 100, "page": page, "search": "Act"},
                headers={"User-Agent": UA},
                timeout=60,
                verify=False,
            )
        except Exception as exc:
            log.info("media search fail page=%s: %s", page, exc)
            break
        if r.status_code != 200:
            break
        data = r.json() or []
        if not data:
            break
        _ingest(data)
        if len(data) < 100:
            break

    log.info("media api laws %s", len(items))
    return items


def _filebird_acts() -> list[tuple[str, str]]:
    """Live FileBird document library on /acts/ (official Parliament Acts folder)."""
    items = []
    try:
        import requests
        from requests.packages.urllib3.exceptions import InsecureRequestWarning
        requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
    except Exception:
        return items
    try:
        s = requests.Session()
        s.headers.update(
            {
                "User-Agent": UA,
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )
        page = 1
        while page <= 30:
            payload = {
                "pagination": {"current": page, "limit": 100},
                "search": "",
                "orderBy": "post_title",
                "orderType": "ASC",
                "selectedFolder": [FILEBIRD_ACTS_FOLDER],
            }
            r = s.post(
                "https://www.parlzim.gov.zw/wp-json/filebird/v1/get-attachments",
                json=payload,
                timeout=60,
                verify=False,
            )
            if r.status_code != 200:
                break
            data = r.json() or {}
            files = data.get("files") or []
            if not files:
                break
            for f in files:
                url = _norm(f.get("url") or "")
                if url and _is_law_url(url):
                    items.append((_ident_from_url(url), url))
            max_pages = int(data.get("maxNumPages") or 1)
            if page >= max_pages:
                break
            page += 1
    except Exception as exc:
        log.info("filebird acts fail: %s", exc)
    log.info("filebird acts %s", len(items))
    return items


def discover():
    # items: (ident, url, wayback_ts|None)
    items: list[tuple[str, str, str | None]] = []
    seen: set[str] = set()
    ts_by_url: dict[str, str] = {}

    def add(url: str, ident: str | None = None, ts: str | None = None):
        url = _norm(url)
        if not url or not _is_law_url(url):
            return
        if ts and (url not in ts_by_url or ts > ts_by_url.get(url, "")):
            ts_by_url[url] = ts
        if url in seen:
            return
        seen.add(url)
        items.append((ident or _ident_from_url(url), url, ts))

    # 1) Live WP media
    for ident, url in _media_api_pdfs():
        add(url, ident)

    # 1b) Live FileBird Acts folder
    for ident, url in _filebird_acts():
        add(url, ident)

    # 2) Live seed pages (best-effort href harvest)
    seeds = [
        "https://www.parlzim.gov.zw/acts/",
        "https://www.parlzim.gov.zw/constitution-of-zimbabwe/",
        "https://www.parlzim.gov.zw/",
        "https://www.justice.gov.zw/",
    ]
    for su in seeds:
        try:
            r = live_get(su, ua=UA, verify=False, timeout=(20, 50))
        except Exception as exc:
            log.info("seed fail %s: %s", su, exc)
            continue
        for href in re.findall(r'href=["\']([^"\']+\.pdf[^"\']*)', r.text or "", re.I):
            add(urljoin(su, href))

    # 3) CDX: Parliament acts-list downloads (historic official statute PDFs)
    cdx_limit = env_int("CDX_LIMIT", 5000)
    for prefix in (
        "www.parlzim.gov.zw/acts-list/download/",
        "parlzim.gov.zw/acts-list/download/",
    ):
        for h in cdx_urls(
            prefix,
            limit=cdx_limit,
            match_type="prefix",
            extra_filters=["mimetype:application/pdf"],
        ):
            orig = h.get("original") or ""
            if orig:
                add(orig, ts=h.get("timestamp"))

    # 4) CDX: named Act PDFs under attachments / wp-content
    for prefix in (
        "www.parlzim.gov.zw/attachments/",
        "parlzim.gov.zw/attachments/",
        "www.parlzim.gov.zw/wp-content/uploads/",
        "parlzim.gov.zw/wp-content/uploads/",
        "www.justice.gov.zw/imt/wp-content/uploads/",
        "justice.gov.zw/imt/wp-content/uploads/",
    ):
        for h in cdx_urls(
            prefix,
            limit=cdx_limit,
            match_type="prefix",
            extra_filters=["mimetype:application/pdf"],
        ):
            orig = h.get("original") or ""
            if orig:
                add(orig, ts=h.get("timestamp"))

    # Refresh timestamps onto items
    out = []
    for ident, url, ts in items:
        out.append((ident, url, ts_by_url.get(url) or ts))

    def sort_key(it):
        ident, url, _ts = it
        named = 0 if re.search(r"_ACT_|\.pdf$", ident, re.I) and not re.match(r"^\d+_", ident) else 1
        return (named, ident.lower())

    out = sorted(out, key=sort_key)
    log.info("catalog %s", len(out))
    return out


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 250)
    max_seconds = env_int("MAX_SECONDS", 3600)
    t_start = time.time()
    done = existing_ids(CC)
    ok = skip = fail = 0
    for ident, url, wb_ts in discover():
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        # Prefer CDX-timestamped Wayback replay (historic acts-list live 404s)
        got = fetch_official_prefer_pdf(
            url, ua=UA, verify=False, min_text=150, wayback_ts=wb_ts
        )
        text = got.get("text") or ""
        if got.get("status") != "success" or text.lstrip().startswith("%PDF"):
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error") or "bad_pdf"})
            continue
        if not LAW_MARK.search(text):
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "not_statute_text"})
            continue
        title = _title_from_text(text, ident.replace("-", " "))
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
            collector="collect_zw.py",
            article_re=ART,
            extra_meta={"fetch_method": got.get("method"), "wayback_ts": wb_ts},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s chars=%s method=%s", ident[:70], len(text), got.get("method"))
        else:
            fail += 1
    write_summary(
        CC,
        country=COUNTRY,
        source="Parliament of Zimbabwe (parlzim.gov.zw)",
        source_urls=[
            "https://www.parlzim.gov.zw/",
            "https://www.parlzim.gov.zw/acts/",
            "https://www.justice.gov.zw/",
        ],
        license_text=LICENSE,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage="catalog-backed incomplete (acts-list + FileBird + attachments + media; live acts-list often 404 → timestamped Wayback)",
        notes=(
            "Official Parliament of Zimbabwe Act PDFs. Skipped ZimLII/Veritas/SI. "
            "Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
