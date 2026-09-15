#!/usr/bin/env python3
"""Cayman Islands: legislation.gov.ky (Office of the Law Revision Commissioner /
Portfolio of Legal Affairs) + Official Gazette on gov.ky.

Official-only *.gov.ky / legislation.gov.ky. Live CMS shelves + PhocaDownload
Constitution Orders + CDX of the same official URLs. Not vLex / commercial aggregators.
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import logging, os, re, sys, time
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote, quote, parse_qs
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log, slug_id
from pdf_extract_lib import extract_pdf_text
import requests

CC, COUNTRY, LANG = "ky", "Cayman Islands", "en"
SOURCE_TYPE = "legislation_gov_ky"
LICENSE = (
    "Cayman Islands Government — legislation.gov.ky (Office of the Law Revision "
    "Commissioner, Portfolio of Legal Affairs / Attorney General's Chambers) + "
    "Official Gazette (gov.ky Gazettes / Legislation Gazette). Legislation may be "
    "downloaded and printed for private use; commercial reuse requires permission "
    "from the Attorney General's Chambers. Authentic Official Gazette / Law Revision "
    "Commissioner text prevails. Not legal advice."
)
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
# Commonwealth drafting: Section / s. / Article / Schedule
ART = re.compile(
    r"(?im)^\s*((?:Section|Article|Art\.?|SCHEDULE|Schedule|PART)\s+[0-9]+[A-Za-z]?|"
    r"s\.\s*[0-9]+[A-Za-z]?)\b"
)
log = logging.getLogger("ky")
MAX_PDF = env_int("MAX_PDF_BYTES", 12 * 1024 * 1024)

HOST_OK = (
    "legislation.gov.ky",
    "www.legislation.gov.ky",
    "gov.ky",
    "www.gov.ky",
)
SKIP_RE = re.compile(
    r"(powerpoint|pptx|agenda|newsletter|brochure|order.?of.?the.?day|"
    r"minutes|hansard|favicon|holder__|vacancy|tender|questionnaire|"
    r"organisational.?chart|organizational.?chart|explanatory.?memorandum|"
    r"\bbill\b|/BILLS/|_INTRODUCED|draft-|draft_|draft\s|"
    r"business.?registration.?form|fillable|"
    r"\.docx?$|\.jpe?g$|\.png$|\.doc$)",
    re.I,
)
KEEP_RE = re.compile(
    r"(legislation|gazette|act|acts|constitution|revision|principal|"
    r"subordinate|amending|regulation|order|rules?|statutory|"
    r"/LEGISLATION/|/documents/|phocadownload|\?download=|"
    r"uksi|supplement|extraordinary|proclamation)",
    re.I,
)
CDX_PREFIXES = (
    "legislation.gov.ky/cms/images/LEGISLATION/PRINCIPAL/",
    "www.legislation.gov.ky/cms/images/LEGISLATION/PRINCIPAL/",
    "legislation.gov.ky/cms/images/LEGISLATION/SUBORDINATE/",
    "www.legislation.gov.ky/cms/images/LEGISLATION/SUBORDINATE/",
    "legislation.gov.ky/cms/images/LEGISLATION/AMENDING/",
    "www.legislation.gov.ky/cms/images/LEGISLATION/AMENDING/",
    "legislation.gov.ky/cms/images/LEGISLATION/GAZETTES/",
    "www.legislation.gov.ky/cms/images/LEGISLATION/GAZETTES/",
    "gov.ky/documents/35692/",
    "gov.ky/documents/43485/",
    "www.gov.ky/documents/35692/",
)
LIVE_PAGES = (
    "https://legislation.gov.ky/cms/",
    "https://legislation.gov.ky/cms/legislation/current.html",
    "https://legislation.gov.ky/cms/legislation/current/by-title.html",
    "https://legislation.gov.ky/cms/legislation/current/by-subject.html",
    "https://legislation.gov.ky/cms/legislation/list-of-substantive-acts-by-year.html",
    "https://legislation.gov.ky/cms/legislation/secondary-made-by-year.html",
    "https://legislation.gov.ky/cms/legislation/recent-changes.html",
    "https://legislation.gov.ky/cms/gazettes/gazettes-by-type.html",
    "https://legislation.gov.ky/cms/gazettes/gazettes-by-year.html",
    "https://legislation.gov.ky/cms/legislation/constitution/current.html",
    "https://legislation.gov.ky/cms/legislation/constitution/historic.html",
    "https://gov.ky/web/gazettes",
    "https://gov.ky/web/gazettes/legislation-gazette-supplements",
    "https://gov.ky/web/gazettes/extraordinary-gazettes",
)
# PhocaDownload constitution seeds (resolved live with warmed cookies)
SEED_CONST = (
    (
        "https://legislation.gov.ky/cms/legislation/constitution/current.html"
        "?download=55:the-cayman-islands-constitution-order-2009-uksi-1379-2009",
        "The Cayman Islands Constitution Order 2009 (UKSI 1379:2009)",
        "CONSTITUTION",
    ),
    (
        "https://legislation.gov.ky/cms/legislation/constitution/current.html"
        "?download=56:the-cayman-islands-constitution-amendment-order-2016-uksi-780-2016",
        "The Cayman Islands Constitution (Amendment) Order 2016 (UKSI 780:2016)",
        "CONSTITUTION",
    ),
    (
        "https://legislation.gov.ky/cms/legislation/constitution/current.html"
        "?download=97:the-cayman-islands-constitution-amendment-order-2020-uksi-2020-1283",
        "The Cayman Islands (Constitution) (Amendment) Order 2020 (UKSI 2020:1283)",
        "CONSTITUTION",
    ),
)

_SESSION: requests.Session | None = None


def _warm(sess: requests.Session) -> None:
    """Soft-WAF cookies required for /cms/images/LEGISLATION/ PDFs."""
    try:
        r = sess.get("https://legislation.gov.ky/cms/", timeout=45)
        if r.status_code == 403:
            time.sleep(2)
            r = sess.get("https://legislation.gov.ky/cms/", timeout=45)
        log.info("warmed legislation.gov.ky status=%s cookies=%s", r.status_code, list(sess.cookies.keys()))
    except Exception as exc:
        log.warning("cookie warm fail: %s", exc)


def _session() -> requests.Session:
    global _SESSION
    if _SESSION is not None:
        return _SESSION
    sess = requests.Session()
    sess.headers.update(
        {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
            "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
        }
    )
    sess.verify = False
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass
    _warm(sess)
    _SESSION = sess
    return sess


def _get(sess: requests.Session, url: str, timeout: int = 60, referer: str = "") -> requests.Response:
    headers = {"Referer": referer or "https://legislation.gov.ky/cms/"}
    r = sess.get(url, timeout=timeout, headers=headers, allow_redirects=True)
    if r.status_code == 403 and "legislation.gov.ky" in url:
        _warm(sess)
        time.sleep(1.5)
        r = sess.get(url, timeout=timeout, headers=headers, allow_redirects=True)
    return r


def _norm(url: str) -> str:
    url = (url or "").split("#")[0].strip()
    if not url:
        return url
    host = (urlparse(url).hostname or "").lower()
    # Keep Phoca ?download= query; strip cache-busters on other PDFs
    if "?" in url:
        if "download=" in url.lower():
            pass
        elif ".pdf" in url.lower() or "/documents/" in url.lower():
            # gov.ky Liferay docs need the UUID path segment; drop only trailing ?t=
            if "/documents/" in url and re.search(r"/[0-9a-f-]{20,}", url, re.I):
                # keep path; drop query
                url = url.split("?")[0]
            else:
                url = url.split("?")[0]
    if host.endswith("gov.ky") or host.endswith("legislation.gov.ky"):
        url = url.replace("http://", "https://").replace(":80/", "/")
    if host == "www.legislation.gov.ky":
        url = url.replace("://www.legislation.gov.ky", "://legislation.gov.ky", 1)
    # Encode spaces in LEGISLATION paths
    try:
        parts = urlparse(url)
        if parts.path and (" " in parts.path or any(ord(c) < 33 for c in parts.path)):
            segs = parts.path.split("/")
            enc = "/".join(quote(unquote(s), safe=".-_()%~") for s in segs)
            url = parts._replace(path=enc).geturl()
    except Exception:
        pass
    return url


def _host_ok(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(h == host or host.endswith("." + h) for h in HOST_OK) or host.endswith(".gov.ky")


def _category(url: str, hint: str = "") -> str:
    blob = f"{url} {hint}".lower()
    path = unquote(urlparse(url).path).lower()
    if "constitut" in blob or "uksi" in blob or "download=" in blob and "constitut" in blob:
        return "CONSTITUTION"
    # gov.ky Liferay gazette / supplement PDFs (path has /documents/)
    if "/documents/" in path:
        if "bill" in blob or "introduced" in blob:
            return ""
        return "GAZETTE"
    if "/principal/" in path:
        return "PRINCIPAL"
    if "/subordinate/" in path:
        return "SUBORDINATE"
    if "/amending/" in path:
        return "AMENDING"
    if "/gazettes/" in path or "gazette" in blob or "extraordinary" in blob:
        return "GAZETTE"
    if re.search(r"\bact\s+\d+\s+of\s+\d{4}|\brevision\b", blob) and "/bills/" not in path:
        return "PRINCIPAL"
    if re.search(r"\bact\b", blob) and "bill" not in blob:
        return "PRINCIPAL"
    return ""


def _ident_from_url(url: str, hint: str = "") -> str:
    """Stable id: prefer LEGISLATION year-number code; drop _g / Revision noise for dedupe."""
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    if "download" in qs:
        raw = qs["download"][0]
        # 55:the-cayman-islands-constitution-order-2009-uksi-1379-2009
        slug = raw.split(":", 1)[-1] if ":" in raw else raw
        slug = re.sub(r"[^\w.\-]+", "_", slug).strip("_")[:160]
        if "explanatory" in slug.lower():
            return ""
        return f"constitution_{slug}"[:160]
    path = unquote(parsed.path)
    # .../PRINCIPAL/2016/2016-0006/2016-0006_2024 Revision.pdf
    m = re.search(
        r"/(PRINCIPAL|SUBORDINATE|AMENDING|GAZETTES)/(\d{4}[^/]*)/([^/]+)/([^/]+?)(?:_g)?\.pdf$",
        path,
        re.I,
    )
    if m:
        kind, _yr, code, stem = m.groups()
        kind_l = kind.lower()
        # Prefer instrument code as key so Revision/_g/Act variants collapse
        base = re.sub(r"[^\w.\-]+", "_", code).strip("_")
        # Keep gazette issue stems distinct (2026-L039 vs 2026-3006)
        if kind_l == "gazettes":
            stem_c = re.sub(r"[^\w.\-]+", "_", stem).strip("_")
            return f"gazette_{stem_c}"[:160]
        if kind_l == "amending":
            return f"amending_{base}"[:160]
        if kind_l == "subordinate":
            return f"sl_{base}"[:160]
        return f"act_{base}"[:160]
    # gov.ky Liferay: /documents/.../Title.pdf/<uuid>
    if "/documents/" in path:
        parts = [unquote(p) for p in path.split("/") if p]
        title_seg = ""
        for p in parts:
            pl = p.lower()
            if pl.endswith(".pdf") and not re.match(r"^[0-9a-f-]{20,}\.pdf$", pl):
                title_seg = p[:-4] if pl.endswith(".pdf") else p
        if not title_seg and hint:
            title_seg = hint
        if title_seg:
            h = re.sub(r"[^\w.\-]+", "_", title_seg).strip("_")[:140]
            if h and not re.match(r"^[0-9a-f-]{20,}$", h, re.I):
                return f"gazette_{h}"[:160]
        return ("gazette_" + re.sub(r"[^\w.\-]+", "_", Path(path).stem)).strip("_")[:160]
    if hint:
        h = re.sub(r"[^\w.\-]+", "_", hint).strip("_")[:160]
        if h and len(h) > 6:
            return h
    return (Path(path).stem or "doc")[:160]


def _rank(ident: str, cat: str, url: str) -> int:
    blob = f"{ident} {cat} {url}".lower()
    path = unquote(urlparse(url).path)
    if cat == "CONSTITUTION" or "constitut" in blob:
        return 0
    # Prefer current Revision consolidations over historic Act-of-year / _g duplicates
    is_rev = bool(re.search(r"\d{4}\s*Revision", path, re.I)) or "revision" in blob
    is_g = path.lower().endswith("_g.pdf") or "_g.pdf" in path.lower()
    year_m = re.search(r"(20[12]\d|19\d\d)", path)
    year = int(year_m.group(1)) if year_m else 0
    if cat == "PRINCIPAL" or "/principal/" in blob:
        if is_rev and not is_g and year >= 2020:
            return 1
        if is_rev and not is_g:
            return 2
        if is_rev:
            return 3
        return 4
    if cat == "SUBORDINATE" or "/subordinate/" in blob:
        return 5
    if cat == "AMENDING" or "/amending/" in blob:
        return 6
    if cat == "GAZETTE" or "gazette" in blob:
        # Prefer Legislation Gazette / consolidated indices over ordinary extras
        if "legislation" in blob or "consolidated" in blob or re.search(r"20\d{2}-3\d{3}", blob):
            return 7
        return 8
    return 9


def _prefer_url(new: str, old: str) -> bool:
    """True if new URL is better than old for same ident."""
    n, o = unquote(new).lower(), unquote(old).lower()
    # Prefer non-_g
    if n.endswith("_g.pdf") and not o.endswith("_g.pdf"):
        return False
    if o.endswith("_g.pdf") and not n.endswith("_g.pdf"):
        return True
    # Prefer Revision over Act N of YYYY
    n_rev = "revision" in n
    o_rev = "revision" in o
    if n_rev and not o_rev:
        return True
    if o_rev and not n_rev:
        return False
    # Prefer higher revision year in filename
    def rev_year(u: str) -> int:
        m = re.search(r"(20\d{2})\s*revision", u, re.I)
        return int(m.group(1)) if m else 0
    if rev_year(n) != rev_year(o):
        return rev_year(n) > rev_year(o)
    return False


def discover():
    items, seen_url, best = [], set(), {}

    def add(url, ts="", title_hint="", cat=""):
        url = _norm(url)
        if not url:
            return
        low = url.lower()
        is_phoca = "download=" in low
        is_pdf = ".pdf" in low or is_phoca
        if not is_pdf:
            return
        if not _host_ok(url):
            return
        blob = f"{low} {title_hint} {cat}"
        if SKIP_RE.search(blob):
            return
        if not KEEP_RE.search(blob) and not is_phoca:
            return
        # Hard skip bills folder
        if "/bills/" in low or "_introduced" in low:
            return
        cat = cat or _category(url, title_hint)
        if not cat and not is_phoca:
            # allow gazette-ish gov.ky docs only when KEEP matched
            if "/documents/" in low and "gazette" not in blob and "legislation" not in blob and "made" not in blob:
                return
            if "/documents/" in low:
                cat = "GAZETTE"
            else:
                return
        ident = _ident_from_url(url, title_hint)
        if not ident:
            return
        if url in seen_url:
            return
        seen_url.add(url)
        row = (ident, url, (title_hint or "").strip()[:200], cat, ts or "")
        prev = best.get(ident)
        if prev is None:
            best[ident] = row
        else:
            # better category rank, or better URL variant
            if _rank(row[0], row[3], row[1]) < _rank(prev[0], prev[3], prev[1]):
                best[ident] = row
            elif _rank(row[0], row[3], row[1]) == _rank(prev[0], prev[3], prev[1]):
                if _prefer_url(row[1], prev[1]) or (ts or "") > (prev[4] or ""):
                    best[ident] = row

    for url, hint, cat in SEED_CONST:
        add(url, "", hint, cat)

    sess = _session()

    for page in LIVE_PAGES:
        try:
            r = _get(sess, page, timeout=60)
            if r.status_code != 200:
                log.warning("live %s status=%s", page, r.status_code)
                continue
            before = len(best)
            # Standard PDF hrefs
            for href in re.findall(r'href=["\']([^"\']+)["\']', r.text, re.I):
                full = urljoin(r.url, href)
                tip = ""
                if "download=" in full.lower():
                    # Phoca title from slug
                    m = re.search(r"download=\d+:([^\"'&]+)", full, re.I)
                    tip = (m.group(1) if m else "").replace("-", " ")[:200]
                    if "explanatory" in tip.lower():
                        continue
                    add(full, "", tip, "CONSTITUTION" if "constitut" in tip.lower() or "constitut" in page else "")
                    continue
                if ".pdf" not in full.lower():
                    continue
                tip = Path(unquote(urlparse(full).path)).stem
                tip = tip.replace("_", " ").replace("+", " ")[:200]
                # Prefer title from link text when available later; stem OK
                add(full, "", tip)
            # Link text for better titles
            for href, tip_html in re.findall(
                r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', r.text, re.I | re.S
            ):
                tip = re.sub(r"<[^>]+>", "", tip_html).strip()
                if len(tip) < 5:
                    continue
                full = urljoin(r.url, href)
                if ".pdf" in full.lower() or "download=" in full.lower():
                    if "explanatory memorandum" in tip.lower():
                        continue
                    cat = ""
                    if "constitut" in tip.lower():
                        cat = "CONSTITUTION"
                    add(full, "", tip[:200], cat)
            log.info("live %s +%s catalog=%s", page.split("/")[-1], len(best) - before, len(best))
        except Exception as exc:
            log.warning("live %s fail: %s", page, exc)

    lim = env_int("CDX_LIMIT", 1500)
    for prefix in CDX_PREFIXES:
        try:
            before = len(best)
            for h in cdx_urls(
                prefix,
                limit=lim,
                match_type="prefix",
                extra_filters=["mimetype:application/pdf"],
            ):
                orig = h.get("original") or ""
                ts = h.get("timestamp") or ""
                if not orig:
                    continue
                if "/BILLS/" in orig or "/bills/" in orig:
                    continue
                tip = Path(unquote(urlparse(orig).path)).stem.replace("_", " ")[:200]
                add(orig, ts, tip)
            log.info("cdx %s +%s catalog=%s", prefix, len(best) - before, len(best))
        except Exception as exc:
            log.warning("cdx %s fail: %s", prefix, exc)

    items = list(best.values())
    items.sort(key=lambda it: (_rank(it[0], it[3], it[1]), it[1]))
    log.info("catalog %s", len(items))
    return items


def ocr_pdf(raw: bytes) -> tuple[str, str, int]:
    os.environ.setdefault("TESSDATA_PREFIX", "/home/box/tessdata")
    ocr_pages = env_int("OCR_PAGES", 10)
    return extract_pdf_text(raw, enable_ocr=True, ocr_lang="eng", ocr_max_pages=ocr_pages)


def fetch_pdf(url: str, wayback_ts: str = "") -> dict:
    """Live session (cookie-warmed) first; fetch_official/Wayback fallback."""
    sess = _session()
    url = _norm(url)
    try:
        # Accept header for PDFs
        sess.headers["Accept"] = "application/pdf,application/octet-stream,text/html,*/*;q=0.8"
        r = _get(
            sess,
            url,
            timeout=90,
            referer="https://legislation.gov.ky/cms/legislation/current.html",
        )
        body = r.content or b""
        ctype = r.headers.get("content-type") or ""
        if r.status_code == 200 and body[:4] == b"%PDF" and len(body) <= MAX_PDF:
            # reuse world_lib pdftotext via fetch_official path: local extract
            from world_lib import pdf_to_text
            text = pdf_to_text(body)
            if text and len(text) >= 120:
                return {
                    "status": "success",
                    "text": text,
                    "content": body,
                    "method": "http_pdf_session",
                    "error": "",
                    "source_url": url,
                }
            text2, how, pages = ocr_pdf(body)
            if text2 and len(text2) >= 100:
                return {
                    "status": "success",
                    "text": text2,
                    "content": body,
                    "method": f"ocr:{how}",
                    "error": "",
                    "source_url": url,
                }
            # fall through to wayback if extract failed
    except Exception as exc:
        log.debug("session fetch fail %s: %s", url[:80], exc)

    got = fetch_official(
        url, ua=UA, verify=False, min_text=120, wayback_ts=wayback_ts or None
    )
    if got.get("status") == "success":
        return got
    raw = got.get("content") or b""
    if isinstance(raw, bytes) and raw[:4] == b"%PDF" and len(raw) <= MAX_PDF:
        text, how, pages = ocr_pdf(raw)
        if text and len(text) >= 100:
            got.update(status="success", text=text, method=f"ocr:{how}", error="")
            return got
        got["error"] = (got.get("error") or "") + f";ocr_failed:{how}"
    return got


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 175)
    max_seconds = env_int("MAX_SECONDS", 3600)
    t_start = time.time()
    done = existing_ids(CC)
    ok = skip = fail = ocr_used = 0
    for ident, url, hint, cat, ts in discover():
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        got = fetch_pdf(url, ts)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error")})
            continue
        if "ocr" in str(got.get("method") or "").lower():
            ocr_used += 1
        title = hint or None
        if not title:
            for line in text.splitlines():
                if len(line.strip()) > 18:
                    title = line.strip()[:240]
                    break
        if cat and title and cat.lower() not in title.lower():
            title = f"{title} [{cat}]"
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title or ident, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_ky.py",
            article_re=ART,
            extra_meta={"fetch_method": got.get("method"), "category": cat, "wayback_ts": ts},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s", ident[:70], got.get("method"), len(text))
        else:
            fail += 1
    write_summary(
        CC,
        country=COUNTRY,
        source="Cayman Islands legislation.gov.ky / Official Gazette (gov.ky)",
        source_urls=[
            "https://legislation.gov.ky/cms/",
            "https://legislation.gov.ky/cms/legislation/current.html",
            "https://legislation.gov.ky/cms/legislation/current/by-title.html",
            "https://legislation.gov.ky/cms/legislation/list-of-substantive-acts-by-year.html",
            "https://legislation.gov.ky/cms/legislation/secondary-made-by-year.html",
            "https://legislation.gov.ky/cms/legislation/constitution/current.html",
            "https://legislation.gov.ky/cms/gazettes/gazettes-by-year.html",
            "https://gov.ky/web/gazettes",
            "https://gov.ky/web/gazettes/legislation-gazette-supplements",
            "https://gov.ky/web/gazettes/extraordinary-gazettes",
        ],
        license_text=LICENSE,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage=(
            "catalog-backed incomplete (legislation.gov.ky PRINCIPAL/SUBORDINATE/"
            "AMENDING/GAZETTES + Constitution Orders + gov.ky Legislation Gazette + CDX)"
        ),
        notes=(
            f"Official legislation.gov.ky (Law Revision Commissioner) PDFs + PhocaDownload "
            f"Constitution Orders (UKSI) + gov.ky Official/Legislation Gazette supplements; "
            f"live cookie-warmed session + Wayback CDX. Prefer Constitution + PRINCIPAL "
            f"Revisions + Subordinate + Amending + Gazettes. Skip bills/explanatory memos/"
            f"charts. OCR eng used={ocr_used}. Not vLex. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s ocr=%s", ok, skip, fail, ocr_used)


if __name__ == "__main__":
    main()
