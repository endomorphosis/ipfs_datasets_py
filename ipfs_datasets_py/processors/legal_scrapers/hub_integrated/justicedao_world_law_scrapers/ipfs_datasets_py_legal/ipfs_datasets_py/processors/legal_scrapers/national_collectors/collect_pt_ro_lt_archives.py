#!/usr/bin/env python3
"""Archive-first harvest for still-blocked PT / RO / LT gazettes.

Uses ipfs_datasets_py web_archiving fallbacks already on disk
(via archive_fallbacks.py: Wayback CDX, Common Crawl CDX/WARC, archive.is).
Does not git clone. Does not touch de/es/fr/nl/ch. Does not start or
duplicate live collect_*.py processes.

Prefer: Wayback CDX -> Common Crawl CDX -> archive.today. Playwright is
used only if the package is importable (it is not in this environment).
Official domains only.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    ROOT,
    base_record,
    corpus_bytes,
    ensure_dirs,
    existing_ids,
    html_to_text,
    iso_date,
    log_failure,
    slug_id,
    utcnow,
    write_instrument,
    write_summary,
    xml_to_text,
)
from archive_fallbacks import (  # noqa: E402
    fetch_common_crawl_warc,
    get_archive_is_content,
    get_wayback_content,
    has_brave_key,
    is_spa_shell,
    search_common_crawl,
    search_wayback_machine,
)

log = logging.getLogger("pt_ro_lt_archives")

MAX_CDX = 2500
MAX_FETCH = 0  # fetch ALL unique official URLs
MIN_TEXT = {
    "pt": 220,
    "ro": 400,
    "lt": 500,
}

GARBAGE_URL_RE = re.compile(
    r"%0[0-9A-Fa-f]|[\x00-\x08\x0b\x0c\x0e-\x1f]|['\"]|%27|%22"
)
CHROME_PATH_RE = re.compile(
    r"(?:/home/?$|/index\.html?$|/$|/contact|/about|/cookies|/privacy|"
    r"/login|/search/?$|/favicon|/css/|/js/|/static/|/web/guest/?$)",
    re.I,
)

try:
    from playwright.sync_api import sync_playwright  # type: ignore

    HAVE_PLAYWRIGHT = True
except Exception:
    HAVE_PLAYWRIGHT = False


SPECS = {
    "pt": {
        "country": "Portugal",
        "lang": "pt",
        "source_type": "dre",
        "license": (
            "Diário da República (dre.pt) official gazette. "
            "Reuse per dre.pt legal notice."
        ),
        "hosts": (
            "dre.pt",
            "data.dre.pt",
            "files.dre.pt",
            "eli.diariodarepublica.pt",
        ),
        "cdx": [
            # Born-digital gazette PDFs. Skip OutSystems detalhe shells.
            {"url": "dre.pt/application/conteudo/*", "limit": MAX_CDX,
             "extra_filters": ["mimetype:application/pdf"]},
            {"url": "dre.pt/application/conteudo/1*", "limit": 500,
             "extra_filters": ["mimetype:application/pdf"]},
            {"url": "dre.pt/application/conteudo/2*", "limit": 400,
             "extra_filters": ["mimetype:application/pdf"]},
            {"url": "dre.pt/application/conteudo/4*", "limit": 400,
             "extra_filters": ["mimetype:application/pdf"]},
            {"url": "dre.pt/application/conteudo/5*", "limit": 400,
             "extra_filters": ["mimetype:application/pdf"]},
            {"url": "dre.pt/application/conteudo/6*", "limit": 400,
             "extra_filters": ["mimetype:application/pdf"]},
            {"url": "dre.pt/application/conteudo/7*", "limit": 400,
             "extra_filters": ["mimetype:application/pdf"]},
            {"url": "dre.pt/application/conteudo/8*", "limit": 400,
             "extra_filters": ["mimetype:application/pdf"]},
            {"url": "dre.pt/application/conteudo/9*", "limit": 400,
             "extra_filters": ["mimetype:application/pdf"]},
            {"url": "dre.pt/application/conteudo/*", "limit": 400,
             "from_date": "20180101", "to_date": "20191231",
             "extra_filters": ["mimetype:application/pdf"]},
            {"url": "dre.pt/application/conteudo/*", "limit": 400,
             "from_date": "20200101", "to_date": "20211231",
             "extra_filters": ["mimetype:application/pdf"]},
            {"url": "dre.pt/application/conteudo/*", "limit": 400,
             "from_date": "20220101", "to_date": "20231231",
             "extra_filters": ["mimetype:application/pdf"]},
            {"url": "dre.pt/application/conteudo/*", "limit": 400,
             "from_date": "20240101", "to_date": "20261231",
             "extra_filters": ["mimetype:application/pdf"]},
            {"url": "dre.pt/application/file/*", "limit": MAX_CDX,
             "extra_filters": ["mimetype:application/pdf"]},
            {"url": "dre.pt/pdf1sdip/*", "limit": 800},
            {"url": "files.dre.pt/1s/*", "limit": 800},
            {"url": "data.dre.pt/eli/*", "limit": 400},
            {"url": "eli.diariodarepublica.pt/*", "limit": 200},
        ],
        "cc": [
            "dre.pt/application/conteudo/*",
            "dre.pt/application/file/*",
            "data.dre.pt/eli/*",
            "files.dre.pt/1s/*",
        ],
        "path_re": re.compile(
            r"/application/(?:conteudo|file)/\d+"
            r"|/eli/"
            r"|/pdf1sdip/.+\.pdf"
            r"|/1s/\d{4}/.+\.pdf",
            re.I,
        ),
        "seeds": [
            "https://dre.pt/application/conteudo/480623",
            "https://data.dre.pt/eli/dec-lei/47344/1966/p/cons/20170803/pt/html",
            "https://data.dre.pt/eli/lei/110/2009/p/cons/20170801/pt/html",
            "https://dre.pt/dre/detalhe/decreto-aprovacao-constituicao/1976-480623",
        ],
        "blocker": (
            "Origin dre.pt / data.dre.pt / files.dre.pt / eli.diariodarepublica.pt "
            "is an OutSystems SPA that error-redirects ('A página não se encontra "
            "disponível'). Live Chrome dump-dom confirms the error page. "
            "Playwright package is not installed. Archive-first harvest of "
            "official consolidations / gazette PDFs."
        ),
    },
    "ro": {
        "country": "Romania",
        "lang": "ro",
        "source_type": "legislatie_just",
        "license": "legislatie.just.ro official portal of the Ministry of Justice.",
        "hosts": ("legislatie.just.ro",),
        "cdx": [
            {"url": "legislatie.just.ro/Public/DetaliiDocumentAfis/*", "limit": MAX_CDX},
            {"url": "legislatie.just.ro/Public/DetaliiDocument/*", "limit": 80},
        ],
        "cc": [
            "legislatie.just.ro/Public/DetaliiDocumentAfis/*",
            "legislatie.just.ro/Public/DetaliiDocument/*",
        ],
        "path_re": re.compile(r"DetaliiDocument(?:Afis)?/\s*\d+", re.I),
        "seeds": [
            "http://legislatie.just.ro/Public/DetaliiDocumentAfis/1",
            "https://legislatie.just.ro/Public/DetaliiDocumentAfis/2",
            "https://legislatie.just.ro/Public/DetaliiDocument/1",
        ],
        "blocker": (
            "Origin legislatie.just.ro TCP-resets / RemoteDisconnected from this "
            "collector network. Wayback snapshots of act pages (DetaliiDocumentAfis "
            "is the server-rendered display view)."
        ),
    },
    "lt": {
        "country": "Lithuania",
        "lang": "lt",
        "source_type": "etar",
        "license": (
            "TAR / e-tar.lt official legal acts. Open-data slice often CC BY 4.0 "
            "on data.gov.lt when Spinta is up."
        ),
        "hosts": ("e-tar.lt", "www.e-tar.lt"),
        "cdx": [
            {"url": "www.e-tar.lt/portal/lt/legalAct/*", "limit": MAX_CDX},
            {"url": "e-tar.lt/portal/lt/legalAct/*", "limit": 800},
            {"url": "www.e-tar.lt/portal/legalAct.html*", "limit": MAX_CDX},
            {"url": "www.e-tar.lt/portal/lt/legalAct/TAR.*", "limit": 800},
            {"url": "www.e-tar.lt/portal/lt/legalAct/0*", "limit": 250},
            {"url": "www.e-tar.lt/portal/lt/legalAct/1*", "limit": 250},
            {"url": "www.e-tar.lt/portal/lt/legalAct/2*", "limit": 250},
            {"url": "www.e-tar.lt/portal/lt/legalAct/3*", "limit": 250},
            {"url": "www.e-tar.lt/portal/lt/legalAct/4*", "limit": 250},
            {"url": "www.e-tar.lt/portal/lt/legalAct/5*", "limit": 250},
            {"url": "www.e-tar.lt/portal/lt/legalAct/6*", "limit": 250},
            {"url": "www.e-tar.lt/portal/lt/legalAct/7*", "limit": 250},
            {"url": "www.e-tar.lt/portal/lt/legalAct/8*", "limit": 250},
            {"url": "www.e-tar.lt/portal/lt/legalAct/9*", "limit": 250},
            {"url": "www.e-tar.lt/portal/lt/legalAct/a*", "limit": 250},
            {"url": "www.e-tar.lt/portal/lt/legalAct/b*", "limit": 250},
            {"url": "www.e-tar.lt/portal/lt/legalAct/c*", "limit": 250},
            {"url": "www.e-tar.lt/portal/lt/legalAct/d*", "limit": 250},
            {"url": "www.e-tar.lt/portal/lt/legalAct/e*", "limit": 250},
            {"url": "www.e-tar.lt/portal/lt/legalAct/f*", "limit": 250},
        ],
        "cc": [
            "www.e-tar.lt/portal/lt/legalAct/*",
            "www.e-tar.lt/portal/legalAct.html*",
            "www.e-tar.lt/portal/lt/legalAct/TAR.*",
        ],
        "path_re": re.compile(
            r"/legalAct/(?:TAR\.[A-Z0-9]{12}|[0-9a-f]{8}[0-9a-f-]{4,})"
            r"|legalAct\.html\?[^#]*documentId=",
            re.I,
        ),
        "seeds": [
            "https://www.e-tar.lt/portal/lt/legalAct/TAR.EC4DC009E86D",
            "https://www.e-tar.lt/portal/lt/legalAct/0035e11074d111eb9601893677bfd7d8",
            "https://www.e-tar.lt/portal/lt/legalAct/00554c90ceff11e4bcd1a882e9a189f1/NGIqtUYURf",
        ],
        "blocker": (
            "Origin e-tar.lt returns Cloudflare 403 / JS challenge (Chrome "
            "dump-dom still 'Just a moment...'). get.data.gov.lt Spinta 500s. "
            "Wayback/CC snapshots of TAR consolidations (versioned /legalAct/"
            "{uuid}/{rev} paths hold suvestinė body text)."
        ),
    },
}


def setup_log(cc: str) -> None:
    ensure_dirs(cc)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / cc / "logs" / "archive_collector.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
        force=True,
    )


def cdx_len(rec: dict) -> int:
    try:
        return int(rec.get("length") or rec.get("warc_length") or 0)
    except Exception:
        return 0


def host_ok(url: str, spec: dict) -> bool:
    host = (urlparse(url).hostname or "").lower().lstrip("www.")
    allowed = tuple(h.lower().lstrip("www.") for h in spec["hosts"])
    return any(host == a or host.endswith("." + a) for a in allowed)


def url_garbage(url: str) -> bool:
    if not url or not url.startswith("http"):
        return True
    path = urlparse(url).path or ""
    if GARBAGE_URL_RE.search(url) and not re.search(r"DetaliiDocument", url, re.I):
        # RO CDX sometimes encodes a leading space as %20 before the id.
        if re.search(r"DetaliiDocument(?:Afis)?/%20?\d+", url, re.I):
            return False
        return True
    if re.search(r"/%20", path) and "DetaliiDocument" not in path:
        return True
    if re.search(r"legalAct/%0", url, re.I):
        return True
    return False


def path_ok(url: str, spec: dict) -> bool:
    if url_garbage(url):
        return False
    path = urlparse(url).path or "/"
    if CHROME_PATH_RE.search(path) and not spec["path_re"].search(url):
        return False
    return bool(spec["path_re"].search(url))


def ident_from_url(cc: str, url: str) -> str:
    p = urlparse(url)
    path = unquote(p.path or "")
    q = parse_qs(p.query)
    if cc == "pt":
        m = re.search(r"/conteudo/(\d+)", path)
        if m:
            return m.group(1)
        m = re.search(r"/application/file/(\d+)", path)
        if m:
            return f"file-{m.group(1)}"
        m = re.search(r"/detalhe/([^/]+)/(\d+(?:-\d+)?)", path)
        if m:
            return f"{m.group(1)}-{m.group(2)}"
        m = re.search(r"/eli/(.+)$", path)
        if m:
            return m.group(1).replace("/", "-")
        m = re.search(r"/search/(\d+)/", path)
        if m:
            return m.group(1)
        m = re.search(r"/pdf1sdip/(.+\.pdf)$", path, re.I)
        if m:
            return "pdf1s-" + m.group(1).replace("/", "-")
        m = re.search(r"/1s/(.+\.pdf)$", path, re.I)
        if m:
            return "files-" + m.group(1).replace("/", "-")
    if cc == "ro":
        m = re.search(r"DetaliiDocument(?:Afis)?/\s*(\d+)", path)
        if m:
            return m.group(1)
    if cc == "lt":
        m = re.search(r"/legalAct/(TAR\.[A-Z0-9]{12})(?:/([^/?#]+))?", path, re.I)
        if m:
            return f"{m.group(1)}" + (f"-{m.group(2)}" if m.group(2) else "")
        m = re.search(
            r"/legalAct/([0-9a-f]{8}[0-9a-f-]{4,})(?:/([^/?#]+))?", path, re.I
        )
        if m:
            return m.group(1) + (f"-{m.group(2)}" if m.group(2) else "")
        if q.get("documentId"):
            return q["documentId"][0]
    tail = (path.strip("/") or p.netloc).replace("/", "-")
    return tail[-120:] or "instrument"


def date_from_url_or_ts(url: str, ts: str) -> str | None:
    m = re.search(r"(19|20)\d{2}[-/](0[1-9]|1[0-2])[-/](0[1-9]|[12]\d|3[01])", url)
    if m:
        return iso_date(m.group(0).replace("/", "-"))
    if ts and len(ts) >= 8:
        return iso_date(ts[:8])
    return None


def extract_title(html: str, ident: str) -> str:
    if not html:
        return ident
    m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.I)
    if m:
        t = re.sub(r"\s+", " ", m.group(1)).strip()
        t = re.sub(r"\s*\|\s*Wayback Machine$", "", t)
        t = re.sub(r"^Wayback Machine\s*", "", t)
        t = re.sub(r"\s*-\s*Portal Legislativ$", "", t)
        if 8 < len(t) < 300:
            return t
    for pat in (
        r"<h1[^>]*>([^<]{8,240})</h1>",
        r"<h2[^>]*>([^<]{8,240})</h2>",
        r'class="[^"]*title[^"]*"[^>]*>([^<]{8,240})<',
    ):
        m = re.search(pat, html, re.I)
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip()
    return ident


def pdf_to_text(blob: bytes) -> str:
    if not blob or blob[:4] != b"%PDF":
        return ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(blob)
            path = tmp.name
        try:
            for args in (
                ["pdftotext", "-layout", "-nopgbrk", "-enc", "UTF-8", path, "-"],
                ["pdftotext", "-raw", "-enc", "UTF-8", path, "-"],
                ["pdftotext", "-q", path, "-"],
            ):
                p = subprocess.run(args, capture_output=True, timeout=40)
                text = (p.stdout or b"").decode("utf-8", "replace").strip()
                if len(text) >= 80:
                    return text
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
    except Exception:
        return ""
    return ""


def strip_portal_chrome(cc: str, text: str) -> str:
    if not text:
        return text
    if cc == "lt":
        # Drop TAR portal nav; keep from document title / body markers.
        for marker in (
            "Dokumento struktūra",
            "Patvirtinta ",
            "LIETUVOS RESPUBLIKOS",
            "Lietuvos Respublikos",
            "ĮSAKYMAS",
            "NUTARIMAS",
            "ĮSTATYMAS",
        ):
            i = text.find(marker)
            if i >= 0:
                text = text[i:]
                break
        text = re.sub(
            r"PradžiaNaujausi[\s\S]{0,400}?(Deutsch\s+English\s+Français\s+Lietuvių\s+Русский)",
            "",
            text,
            count=1,
        )
    if cc == "ro":
        text = re.sub(r"^[\s\S]{0,400}?Cuprinsul Actului", "Cuprinsul Actului", text, count=1)
        text = text.replace("Se încarcă, vă rugăm asteptati.", "")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def body_to_text(payload: dict) -> tuple[str, str]:
    ctype = (payload.get("content_type") or "").lower()
    raw_bytes = payload.get("content") or b""
    html = payload.get("text") or ""
    if isinstance(raw_bytes, str):
        raw_bytes = raw_bytes.encode("utf-8", "replace")
    if "pdf" in ctype or (raw_bytes[:4] == b"%PDF"):
        return pdf_to_text(raw_bytes), "pdf"
    if "xml" in ctype or html.lstrip().startswith("<?xml") or "<akoma" in html[:500].lower():
        return xml_to_text(html) or html_to_text(html), "xml"
    if html:
        return html_to_text(html), "html"
    if raw_bytes:
        try:
            return html_to_text(raw_bytes.decode("utf-8", "replace")), "bytes"
        except Exception:
            return "", "unknown"
    return "", "unknown"


def is_low_quality(cc: str, html: str, text: str) -> str | None:
    if is_spa_shell(html, text):
        return "spa_shell"
    if re.search(r"just a moment|cf-browser-verification|checking your browser", html or "", re.I):
        return "cloudflare_challenge"
    if re.search(r"A página não se encontra disponível", html or "", re.I):
        return "pt_error_redirect"
    if cc == "ro" and "Se încarcă" in (text or "") and text.lower().count("articolul") < 3:
        return "ro_js_shell"
    if cc == "lt":
        bodyish = sum(
            1
            for k in ("straipsnis", "punktas", "skyrius", "įstatymas", "nutarimas", "įsakymas")
            if k in text.lower()
        )
        if bodyish == 0 and len(text) < 2500:
            return "lt_chrome_only"
    if len(text) < MIN_TEXT.get(cc, 280):
        return "short_text"
    return None


def consider(hits: dict, url: str, meta: dict, spec: dict, cc: str) -> None:
    if not url or not url.startswith("http"):
        return
    if not host_ok(url, spec):
        return
    if url not in spec.get("seeds", []) and not path_ok(url, spec):
        return
    # drop directory indexes and tiny captures
    mime = (meta.get("mimetype") or meta.get("mime") or "").lower()
    ln = cdx_len(meta)
    if mime.startswith("application/x-directory"):
        return
    if ln and ln < 1500 and mime.startswith("text/html") and cc != "pt":
        # keep PT HTML in case of small but real consolidations; still filtered later
        if url not in spec.get("seeds", []):
            return
    key = re.sub(r"[?#].*$", "", unquote(url)).rstrip("/").lower()
    if cc == "ro":
        m = re.search(r"detaliidocument(?:afis)?/\s*(\d+)", key)
        if m:
            key = f"ro-doc-{m.group(1)}"
    prev = hits.get(key)
    ts = str(meta.get("timestamp") or "")
    score = (ln, ts)
    if prev:
        prev_score = (cdx_len(prev), str(prev.get("timestamp") or ""))
        # Prefer Afis (server-rendered) over DetaliiDocument for RO.
        if cc == "ro":
            prev_afis = "afis" in (prev.get("original") or "").lower()
            now_afis = "afis" in url.lower()
            if now_afis and not prev_afis:
                hits[key] = {**meta, "original": url, "key": key}
                return
            if prev_afis and not now_afis:
                return
        if prev_score >= score:
            return
    hits[key] = {**meta, "original": url, "key": key}


def discover(cc: str, spec: dict) -> tuple[list[dict], list[str]]:
    notes: list[str] = []
    hits: dict[str, dict] = {}
    cache_path = ROOT / cc / "raw" / "cdx_hits.jsonl"

    for seed in spec.get("seeds") or []:
        consider(hits, seed, {"timestamp": "", "source": "seed", "mimetype": "text/html", "length": "0"}, spec, cc)

    for q in spec["cdx"]:
        url = q["url"] if isinstance(q, dict) else q
        kwargs = {
            "limit": q.get("limit", MAX_CDX) if isinstance(q, dict) else MAX_CDX,
            "collapse": "urlkey",
            "from_date": "20000101",
        }
        if isinstance(q, dict):
            if q.get("match_type"):
                kwargs["match_type"] = q["match_type"]
            if q.get("extra_filters"):
                kwargs["extra_filters"] = q["extra_filters"]
            if q.get("from_date"):
                kwargs["from_date"] = q["from_date"]
            if q.get("to_date"):
                kwargs["to_date"] = q["to_date"]
        wb = search_wayback_machine(url, **kwargs)
        notes.append(f"wayback CDX {url} n={len(wb)}")
        log.info("%s wayback %s n=%s", cc, url, len(wb))
        for rec in wb:
            consider(hits, rec.get("original") or "", rec, spec, cc)
            try:
                with cache_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"via": "wayback", "q": url, **{k: rec.get(k) for k in ("timestamp", "original", "mimetype", "length")}}, ensure_ascii=False) + "\n")
            except Exception:
                pass

    for prefix in spec.get("cc") or []:
        cc_hits = search_common_crawl(prefix if "*" in prefix else prefix + "*", limit=400)
        notes.append(f"common_crawl CDX {prefix} n={len(cc_hits)}")
        log.info("%s cc %s n=%s", cc, prefix, len(cc_hits))
        for rec in cc_hits:
            consider(hits, rec.get("original") or rec.get("url") or "", rec, spec, cc)

    items = list(hits.values())

    def sort_key(r: dict) -> tuple:
        url = r.get("original") or ""
        ln = cdx_len(r)
        ts = str(r.get("timestamp") or "")
        # Prefer instrument-like: RO afis, LT versioned consolidations, PT PDFs/ELI
        bonus = 0
        if cc == "ro" and "Afis" in url:
            bonus += 10_000_000
        if cc == "lt" and re.search(r"/legalAct/[^/]+/[^/?#]+", urlparse(url).path or ""):
            bonus += 5_000_000
        if cc == "pt" and "/conteudo/" in url:
            bonus += 8_000_000
        if cc == "pt" and "/eli/" in url:
            bonus += 7_000_000
        if (r.get("mimetype") or "").startswith("application/pdf"):
            bonus += 1_000_000
        return (bonus + ln, ts)

    items.sort(key=sort_key, reverse=True)
    notes.append(
        f"unique instrument URLs={len(items)} playwright={HAVE_PLAYWRIGHT} "
        f"brave_skipped={not has_brave_key()}"
    )
    return items, notes


def fetch_archived(url: str, rec: dict, *, try_archive_is: bool) -> dict:
    """Wayback first, then Common Crawl WARC, then archive.is. No live origin."""
    errors: list[str] = []
    ts = rec.get("timestamp") or None
    if rec.get("source") == "wayback" or ts:
        res = get_wayback_content(url, timestamp=ts)
        if res.get("status") == "success" and (res.get("text") or res.get("content")):
            res.setdefault("method", "wayback")
            return res
        errors.append(f"wayback:{res.get('error')}")
        # try latest wayback if timestamped fetch failed
        if ts:
            res2 = get_wayback_content(url, timestamp=None)
            if res2.get("status") == "success" and (res2.get("text") or res2.get("content")):
                res2.setdefault("method", "wayback")
                return res2
            errors.append(f"wayback_latest:{res2.get('error')}")
    else:
        # seed without timestamp: CDX the exact URL then fetch
        exact = search_wayback_machine(url, limit=5, collapse="digest")
        if exact:
            pick = exact[-1]
            res = get_wayback_content(pick.get("original") or url, timestamp=pick.get("timestamp"))
            if res.get("status") == "success" and (res.get("text") or res.get("content")):
                res.setdefault("method", "wayback")
                return res
            errors.append(f"wayback:{res.get('error')}")
        else:
            res = get_wayback_content(url, timestamp=None)
            if res.get("status") == "success" and (res.get("text") or res.get("content")):
                res.setdefault("method", "wayback")
                return res
            errors.append(f"wayback:{res.get('error')}")

    if rec.get("filename") or rec.get("warc_filename") or rec.get("source") == "common_crawl":
        res = fetch_common_crawl_warc(rec)
        if res.get("status") == "success" and (res.get("text") or res.get("content")):
            res.setdefault("method", "common_crawl")
            return res
        errors.append(f"common_crawl:{res.get('error')}")
        # if we only had a CC URL, try wayback on the original
        if rec.get("source") == "common_crawl":
            res = get_wayback_content(url, timestamp=None)
            if res.get("status") == "success" and (res.get("text") or res.get("content")):
                res.setdefault("method", "wayback")
                return res
            errors.append(f"wayback_after_cc:{res.get('error')}")

    if try_archive_is:
        res = get_archive_is_content(url)
        if res.get("status") == "success":
            res.setdefault("method", "archive_is")
            return res
        errors.append(f"archive_is:{res.get('error')}")

    return {"status": "error", "error": "; ".join(errors) or "all_failed", "original_url": url}


def fetch_playwright(url: str) -> dict:
    if not HAVE_PLAYWRIGHT:
        return {"status": "error", "error": "playwright_not_installed"}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path="/usr/bin/google-chrome",
                headless=True,
                args=["--no-sandbox", "--disable-gpu"],
            )
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(2500)
            html = page.content()
            browser.close()
        return {
            "status": "success",
            "text": html,
            "content": html.encode("utf-8", "replace"),
            "content_type": "text/html",
            "method": "playwright",
            "http_status": 200,
            "final_url": url,
        }
    except Exception as exc:
        return {"status": "error", "error": f"playwright:{exc}"}


def fetch_one(cc: str, spec: dict, rec: dict, done: set[str]) -> str:
    url = rec.get("original") or ""
    ident = ident_from_url(cc, url)
    rid = slug_id(cc, ident)
    if rid in done:
        return "skip"
    payload = fetch_archived(
        url,
        rec,
        try_archive_is=(rec.get("source") == "seed"),
    )
    method = payload.get("method") or "wayback"
    html = payload.get("text") or ""
    text, backend = body_to_text(payload)
    text = strip_portal_chrome(cc, text)
    reason = None
    if payload.get("status") != "success":
        reason = payload.get("error") or "fetch_failed"
    else:
        reason = is_low_quality(cc, html, text)
        if reason and HAVE_PLAYWRIGHT and reason in {"spa_shell", "pt_error_redirect", "cloudflare_challenge", "short_text"}:
            pw = fetch_playwright(url)
            if pw.get("status") == "success":
                payload, method = pw, "playwright"
                html = pw.get("text") or ""
                text, backend = body_to_text(pw)
                text = strip_portal_chrome(cc, text)
                reason = is_low_quality(cc, html, text)

    # RO: if DetaliiDocument is a JS shell, try Afis sibling via wayback
    if cc == "ro" and reason in {"ro_js_shell", "short_text", "spa_shell"}:
        m = re.search(r"DetaliiDocument(?:Afis)?/\s*(\d+)", url, re.I)
        if m and "Afis" not in url:
            alt = re.sub(
                r"DetaliiDocument(?:Afis)?/\s*\d+",
                f"DetaliiDocumentAfis/{m.group(1)}",
                url,
                count=1,
                flags=re.I,
            )
            alt_rec = {**rec, "original": alt, "source": "wayback"}
            payload2 = fetch_archived(alt, alt_rec, try_archive_is=False)
            if payload2.get("status") == "success":
                t2, b2 = body_to_text(payload2)
                t2 = strip_portal_chrome(cc, t2)
                if not is_low_quality(cc, payload2.get("text") or "", t2):
                    payload, text, backend, method, url, html, reason = (
                        payload2,
                        t2,
                        b2,
                        payload2.get("method") or method,
                        alt,
                        payload2.get("text") or "",
                        None,
                    )

    if reason:
        log_failure(
            cc,
            {
                "identifier": ident,
                "source_url": url,
                "status": "failed",
                "reason": reason,
                "method_used": method,
                "n": len(text or ""),
            },
        )
        return "fail"

    title = extract_title(html, ident)
    src = payload.get("wayback_url") or payload.get("archive_url") or payload.get("final_url") or url
    rec_out = base_record(
        cc=cc,
        country=spec["country"],
        language=spec["lang"],
        ident=ident,
        title=title,
        text=text,
        source_url=url,
        source_type=spec["source_type"],
        license_text=spec["license"],
        collector=f"{cc}-archive-fallback",
        eli=url if "/eli/" in url else None,
        date=date_from_url_or_ts(url, str(rec.get("timestamp") or payload.get("capture_timestamp") or "")),
        official_identifier=ident,
        document_type="statute",
        law_status="unknown",
        is_current=None,
        extra_meta={
            "method_used": method,
            "discovery": {
                "method": rec.get("source") or "cdx",
                "seed_url": url,
                "catalog_identifier": rec.get("timestamp") or rec.get("filename") or "",
            },
            "text_extraction": {"source": "archive", "backend": backend},
            "http_status": payload.get("http_status"),
            "content_type": payload.get("content_type"),
            "archive_url": payload.get("wayback_url") or payload.get("archive_url"),
            "capture_timestamp": payload.get("capture_timestamp") or rec.get("timestamp"),
        },
    )
    rec_out["canonical_document_url"] = src
    rec_out["information_url"] = url
    write_instrument(cc, rec_out)
    done.add(rid)
    return "ok"


def harvest(cc: str) -> dict:
    spec = SPECS[cc]
    setup_log(cc)
    t0 = utcnow()
    done = existing_ids(cc)
    items, notes = discover(cc, spec)
    notes.insert(0, spec["blocker"])
    if len(items) > MAX_FETCH:
        notes.append(f"capped fetch {MAX_FETCH} of {len(items)}")
        items = items[:MAX_FETCH]
    ok = skip = fail = 0
    methods: dict[str, int] = {}
    for i, rec in enumerate(items, 1):
        try:
            st = fetch_one(cc, spec, rec, done)
            if st == "ok":
                # count method from latest written file is heavy; parse from rec path later
                pass
        except Exception as exc:
            st = "fail"
            log_failure(cc, {"source_url": rec.get("original"), "status": "failed", "reason": repr(exc)})
            log.exception("fetch fail")
        ok += st == "ok"
        skip += st == "skip"
        fail += st == "fail"
        if i % 10 == 0 or i == len(items):
            log.info("%s progress %s/%s ok=%s skip=%s fail=%s", cc, i, len(items), ok, skip, fail)
            write_summary(
                cc,
                country=spec["country"],
                source="archive fallbacks (wayback|common_crawl|archive_is|playwright)",
                source_urls=[q["url"] if isinstance(q, dict) else q for q in spec["cdx"]],
                license_text=spec["license"],
                discovered=len(items),
                fetched=ok,
                skipped=skip,
                failed=fail,
                coverage="shard" if ok else "catalog-backed incomplete",
                notes="\n".join(notes),
                last_run=utcnow(),
            )
    # method histogram from instruments
    instr = ROOT / cc / "instruments"
    if instr.exists():
        for p in instr.glob("*.json"):
            try:
                recj = json.loads(p.read_text(encoding="utf-8"))
                m = (recj.get("metadata") or {}).get("method_used") or "unknown"
                methods[m] = methods.get(m, 0) + 1
            except Exception:
                pass
    nbytes = corpus_bytes(cc)
    notes.append(f"metadata.method_used histogram={methods}")
    notes.append("brave_search skipped (no API key)" if not has_brave_key() else "brave_search unused")
    notes.append(f"playwright_installed={HAVE_PLAYWRIGHT}")
    notes.append(f"started {t0} instruments_bytes={nbytes}")
    if ok == 0:
        notes.append(
            "No instrument-quality snapshots after CDX+fetch (empty CDX, chrome-only, "
            "image-only PDF, or origin error page). See failures.jsonl."
        )
    coverage = "shard" if ok else ("empty CDX" if not items else "empty CDX or chrome-only")
    write_summary(
        cc,
        country=spec["country"],
        source="archive fallbacks (wayback|common_crawl|archive_is|playwright)",
        source_urls=[q["url"] if isinstance(q, dict) else q for q in spec["cdx"]]
        + list(spec.get("seeds") or []),
        license_text=spec["license"],
        discovered=len(items),
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage=coverage,
        notes="\n".join(notes),
        last_run=utcnow(),
        extra=(
            f"blocker_origin documented; this run uses archives first. "
            f"ok={ok} fail={fail} skip={skip} methods={methods}"
        ),
    )
    log.info("%s DONE disc=%s ok=%s skip=%s fail=%s bytes=%s methods=%s", cc, len(items), ok, skip, fail, nbytes, methods)
    return {"cc": cc, "discovered": len(items), "ok": ok, "skip": skip, "fail": fail, "methods": methods, "bytes": nbytes, "notes": notes}


def main() -> None:
    targets = [a for a in sys.argv[1:] if a in SPECS] or ["pt", "ro", "lt"]
    results = []
    for cc in targets:
        try:
            results.append(harvest(cc))
        except Exception:
            log.exception("country %s crashed", cc)
            spec = SPECS[cc]
            write_summary(
                cc,
                country=spec["country"],
                source="archive fallbacks",
                source_urls=[q["url"] if isinstance(q, dict) else q for q in spec["cdx"]],
                license_text=spec["license"],
                discovered=0,
                fetched=0,
                skipped=0,
                failed=1,
                coverage="catalog-backed incomplete",
                notes=spec["blocker"] + "\ncollector exception; see archive_collector.log",
                last_run=utcnow(),
            )
    print(json.dumps(results, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
