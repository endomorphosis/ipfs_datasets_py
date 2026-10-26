#!/usr/bin/env python3
"""Niger (ne): official laws from gouv.ne / justice / finances / intérieur.

Official only (Niger ISO=ne — NOT Nigeria/ng):
  - https://www.gouv.ne/index.php/textes-fondamentaux/ (Constitution, code électoral, chartes)
  - https://justice.gouv.ne/index.php/publications/textes-de-lois-et-reglements (+ /images/lois/pdfs/)
  - https://finances.gouv.ne/ (PhocaDownload lois de finances / organiques / décrets RGCP; CDX /images/decrets/)
  - https://interieur.gouv.ne/documents/ (décrets organisation)
  - Wayback/CDX of the same official *.gouv.ne / gouv.ne / interieur.gouv.ne URLs

Filter: JO/JOSP fascicules kept; other hosts require loi/ordonnance/décret/constitution/code.
PhocaDownload: GET file page then POST license form (no WAF bypass).
Not AfricanLII / Droit-Afrique. No WAF bypass. Not legal advice.
"""
from __future__ import annotations

import html as html_lib
import logging
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse, quote, urlsplit, urlunsplit, urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import (
    cdx_urls,
    env_int,
    fetch_official,
    live_get,
    pdf_to_text,
    save_instrument,
    setup_log,
    slug_id,
)

CC, COUNTRY, LANG = "ne", "Niger", "fr"
SOURCE_TYPE = "jo_niger_official"
LICENSE = (
    "République du Niger — Portail du Gouvernement (gouv.ne) / Ministère de la Justice "
    "(justice.gouv.ne) / Ministère des Finances (finances.gouv.ne) / Ministère de l'Intérieur "
    "(interieur.gouv.ne). Authentic Journal Officiel / official text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.gouv.ne/; Niger=ne not Nigeria)"
ART = re.compile(r"(?im)^\s*((?:Article|Art\.?)\s+\d+[a-zA-Zº°]?)\b")
log = logging.getLogger("ne")

GOUV = "https://www.gouv.ne"
JUSTICE = "https://justice.gouv.ne"
FINANCES = "https://finances.gouv.ne"
INTERIEUR = "https://interieur.gouv.ne"

ALLOWED_HOST_SUFFIXES = (
    "gouv.ne",
    "gov.ne",
    "interieur.gouv.ne",
    "justice.gouv.ne",
    "finances.gouv.ne",
    "mines.gouv.ne",
    "agriculture.gouv.ne",
    "presidence.ne",
    "anp.ne",
    "assemblee.ne",
    "assembleenationale.ne",
)

KEEP_RE = re.compile(
    r"(loi|ordonnance|ordonn|d[eé]cret|decret|arr[eê]t[eé]|arrete|constitution|code|"
    r"journal.?officiel|\bjosp?\b|\bjo\b|\blf\b|organique|directive|charte|statut|"
    r"texte.?juridique|texte.?fondament)",
    re.I,
)
DROP_RE = re.compile(
    r"(discours|allocution|communique|photo|banner|logo|cv[-_]|biographie|"
    r"rapport[-_ ]annuel|budget[-_ ]citoyen|presentation|organigramme|"
    r"conjoncture|recrutement|\bami\b|lexique|encyclopedie|brochure|guide[-_ ]|"
    r"fiche[-_ ]|politique.?nationale|ong[-_ ]|planning|dpbep|dppd|pap[-_]|"
    r"nigeria|\.gov\.ng\b)",
    re.I,
)
TEXT_KEEP_RE = re.compile(
    r"\b(loi|ordonnance|d[eé]cret|decret|constitution|journal\s+officiel|"
    r"code|bulletin des lois|r[eé]publique du niger|republique du niger|"
    r"assembl[eé]e|conseil national)\b",
    re.I,
)

MAX_PDF_BYTES = 25 * 1024 * 1024

GOUV_PAGES = [
    f"{GOUV}/index.php/textes-fondamentaux",
    f"{GOUV}/index.php/textes-fondamentaux/constitution-de-la-7eme-republique",
    f"{GOUV}/index.php/textes-fondamentaux/code-electoral",
    f"{GOUV}/index.php/textes-fondamentaux/charte-des-partis-politiques",
    f"{GOUV}/index.php/textes-fondamentaux/statut-de-l-opposition",
    f"{GOUV}/index.php/textes-fondamentaux/autres-textes",
    f"{GOUV}/index.php/textes-fondamentaux/reccueil-de-textes",
]

JUSTICE_PAGES = [
    f"{JUSTICE}/index.php/publications/textes-de-lois-et-reglements",
    f"{JUSTICE}/index.php/lois-et-reglements",
    f"{JUSTICE}/index.php/textes-de-lois-et-reglements",
]

FINANCE_INDEXES = [
    f"{FINANCES}/index.php/lois-de-finances",
    f"{FINANCES}/index.php/lois-de-reglement",
    f"{FINANCES}/index.php/archives-loi-de-finances",
    f"{FINANCES}/index.php/archives-loi-de-reglement",
    f"{FINANCES}/index.php/archives-lois-organiques",
    f"{FINANCES}/index.php/budget-1/reglementations-budgetaires/textes-portant-elaboration",
    f"{FINANCES}/index.php/budget-1/reglementations-budgetaires/textes-portant-modalites-d-execution-du-budget-de-l-etat",
    f"{FINANCES}/index.php/budget-1/reglementations-budgetaires/directives-uemoa",
    f"{FINANCES}/index.php/budget-1/reglementations-budgetaires/modalites-d-execution-du-budget",
    f"{FINANCES}/index.php/le-ministere/historique/les-textes-portant-organisation",
    f"{FINANCES}/index.php/le-ministere/historique/textes-portant-attributions",
]

INTERIEUR_PAGES = [
    f"{INTERIEUR}/documents/",
    f"{INTERIEUR}/index.php/documents/",
    f"{INTERIEUR}/documents/decret/",
    f"{INTERIEUR}/documents/direction-generale-des-affaires-politiques-et-juridiques/",
]


def _host_ok(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    if host.endswith(".gov.ng") or host.endswith(".ng") and not host.endswith(".gouv.ne"):
        # Hard block Nigeria / wrong TLD leakage (except .gouv.ne already matched)
        if host.endswith(".gov.ng") or host == "nigeria.gov.ng":
            return False
    return any(host == s or host.endswith("." + s) for s in ALLOWED_HOST_SUFFIXES)


def _norm_url(url: str) -> str:
    if not url:
        return ""
    url = html_lib.unescape(url.strip())
    url = url.replace(":80/", "/").replace(":80?", "?")
    if url.startswith("http://"):
        url = "https://" + url[len("http://") :]
    # Prefer non-www justice host (live)
    url = url.replace("https://www.justice.gouv.ne/", "https://justice.gouv.ne/")
    url = url.replace("https://www.finances.gouv.ne/", "https://finances.gouv.ne/")
    url = url.replace("https://www.interieur.gouv.ne/", "https://interieur.gouv.ne/")
    try:
        p = urlsplit(url)
        parts = []
        for seg in p.path.split("/"):
            if not seg:
                parts.append(seg)
                continue
            parts.append(seg if "%" in seg else quote(seg, safe="._-()[]',°"))
        url = urlunsplit((p.scheme or "https", p.netloc, "/".join(parts), "", ""))
    except Exception:
        url = url.replace(" ", "%20")
    return url


def _wayback_orig(url: str) -> str:
    u = html_lib.unescape((url or "").strip())
    u = u.replace(":80/", "/").replace(":80?", "?")
    if u.startswith("https://"):
        u = "http://" + u[len("https://") :]
    return u


def _ident_from_url(url: str) -> str:
    path = unquote(urlparse(url).path)
    name = Path(path).name
    if "/file/" in path:
        # Phoca: .../file/1303-ordonnance-n-2025-44
        slug = path.rstrip("/").split("/file/")[-1]
        return re.sub(r"\W+", "-", slug).strip("-").lower()[:160]
    stem = Path(name).stem
    return re.sub(r"\W+", "-", stem).strip("-").lower()[:160] or re.sub(r"\W+", "-", url)[-80:]


def _title_from_url(url: str) -> str:
    if "/file/" in unquote(urlparse(url).path):
        slug = unquote(urlparse(url).path).rstrip("/").split("/file/")[-1]
        # drop leading numeric id
        slug = re.sub(r"^\d+-", "", slug)
        return slug.replace("-", " ").replace("_", " ")[:240]
    name = unquote(Path(urlparse(url).path).name)
    stem = Path(name).stem
    return stem.replace("_", " ").replace("-", " ")[:240] or stem


def _is_jo(url: str, title: str | None = None) -> bool:
    blob = unquote(urlparse(url).path) + " " + (title or "")
    return bool(re.search(r"(?i)(\bjosp?\b|journal.?officiel|/jo/)", blob))


def _keep_name(url: str, title: str | None = None) -> bool:
    if _is_jo(url, title):
        return True
    blob = unquote(urlparse(url).path) + " " + (title or "")
    if DROP_RE.search(blob) and not KEEP_RE.search(blob):
        return False
    if DROP_RE.search(blob) and re.search(r"(?i)(lexique|encyclopedie|conjoncture|ong[-_]|brochure|guide)", blob):
        return False
    return bool(KEEP_RE.search(blob))


def _add(items, seen, ident, url, meta=None):
    url = _norm_url(url)
    if not url or not _host_ok(url):
        return
    # Direct PDF or Phoca /file/ page
    low = url.lower()
    is_phoca = "/file/" in low and "finances.gouv.ne" in low
    if ".pdf" not in low and not is_phoca:
        return
    key = url.lower()
    if key in seen:
        return
    title = (meta or {}).get("title")
    if not _keep_name(url, title):
        return
    seen.add(key)
    ident = re.sub(r"\W+", "-", (ident or _ident_from_url(url)).strip("-")).lower()[:160]
    items.append((ident, url, meta or {}))


def ocr_pdf(raw: bytes) -> str:
    max_pages = env_int("MAX_OCR_PAGES", 15)
    dpi = env_int("OCR_DPI", 150)
    try:
        with tempfile.TemporaryDirectory() as td:
            pdf = Path(td) / "doc.pdf"
            pdf.write_bytes(raw)
            proc = subprocess.run(
                ["pdftoppm", "-png", "-r", str(dpi), "-f", "1", "-l", str(max_pages), str(pdf), str(Path(td) / "p")],
                check=False,
                capture_output=True,
                timeout=240,
            )
            if proc.returncode != 0:
                return ""
            chunks = []
            for img in sorted(Path(td).glob("p*.png")):
                tproc = subprocess.run(
                    ["tesseract", str(img), "stdout", "-l", "fra", "--psm", "6"],
                    check=False,
                    capture_output=True,
                    timeout=120,
                )
                if tproc.returncode == 0 and tproc.stdout:
                    chunks.append(tproc.stdout.decode("utf-8", "replace").strip())
            return "\n\n".join(c for c in chunks if c).strip()
    except Exception as exc:
        log.warning("ocr_pdf: %s", exc)
        return ""


def fetch_phoca_pdf(file_url: str) -> dict:
    """GET PhocaDownload file page, POST license form, return PDF bytes."""
    out = {
        "status": "error",
        "text": "",
        "content": b"",
        "source_url": file_url,
        "method": "",
        "error": "",
    }
    try:
        import requests
        from requests.packages.urllib3.exceptions import InsecureRequestWarning

        requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
        sess = requests.Session()
        headers = {"User-Agent": UA, "Accept": "text/html,application/pdf,*/*"}
        r = sess.get(file_url, timeout=(20, 90), headers=headers, verify=False)
        html = r.text or ""
        if r.status_code != 200:
            out["error"] = f"phoca_page_http_{r.status_code}"
            return out
        m = re.search(
            r'<form[^>]*(?:id="phocadownloadform"|name="phocaDownloadForm")[^>]*>(.*?)</form>',
            html,
            re.I | re.S,
        )
        if not m:
            out["error"] = "phoca_form_missing"
            return out
        form = m.group(0)
        action_m = re.search(r'action=["\']([^"\']+)["\']', form, re.I)
        action = html_lib.unescape(action_m.group(1)) if action_m else file_url
        post = {}
        for inp in re.findall(r"<input[^>]*>", form, re.I):
            name_m = re.search(r'name=["\']([^"\']+)["\']', inp, re.I)
            val_m = re.search(r'value=["\']([^"\']*)["\']', inp, re.I)
            typ_m = re.search(r'type=["\']([^"\']*)["\']', inp, re.I)
            if not name_m:
                continue
            n = name_m.group(1)
            v = val_m.group(1) if val_m else ""
            t = (typ_m.group(1) if typ_m else "").lower()
            if t == "submit":
                post[n] = v or "Télécharger"
            else:
                post[n] = v
        if "download" not in post:
            out["error"] = "phoca_no_download_id"
            return out
        headers2 = {
            "User-Agent": UA,
            "Accept": "application/pdf,*/*",
            "Referer": file_url,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        r2 = sess.post(
            action,
            data=post,
            timeout=(20, 120),
            headers=headers2,
            verify=False,
            allow_redirects=True,
        )
        body = r2.content or b""
        ctype = (r2.headers.get("content-type") or "").lower()
        if body[:4] == b"%PDF" or "pdf" in ctype:
            if len(body) > MAX_PDF_BYTES:
                out["error"] = f"pdf_too_large:{len(body)}"
                return out
            text = pdf_to_text(body)
            if len(re.sub(r"[\x0c\s]+", "", text or "")) >= 100:
                out.update(status="success", text=text, content=body, method="phoca_post_pdf")
                return out
            # OCR fallback for scanned LF cahiers
            if env_int("OCR_PHOCA", 1) == 1 and len(body) <= env_int("MAX_OCR_BYTES", 8 * 1024 * 1024):
                ocr = ocr_pdf(body)
                if len(ocr) >= 100:
                    out.update(status="success", text=ocr, content=body, method="phoca_post_pdf_ocr_fra")
                    return out
            out["error"] = "phoca_pdf_extract_failed"
            out["content"] = body
            return out
        out["error"] = f"phoca_not_pdf:ctype={ctype}:len={len(body)}"
        return out
    except Exception as exc:
        out["error"] = f"phoca:{exc}"
        return out


def fetch_ne(url: str, *, wayback_ts: str | None = None, allow_ocr: bool = True, phoca: bool = False) -> dict:
    if phoca or ("/file/" in url and "finances.gouv.ne" in url):
        got = fetch_phoca_pdf(url)
        if got.get("status") == "success":
            return got
        # fall through to try wayback of same URL (rarely works for POST) — skip
        return got

    got = fetch_official(url, ua=UA, verify=False, min_text=100, wayback=True, wayback_ts=wayback_ts)
    if got.get("status") == "success":
        return got

    body_for_ocr = got.get("content") or b""
    if wayback_ts:
        try:
            import archive_fallbacks as af

            w = af.get_wayback_content(_wayback_orig(url), timestamp=wayback_ts)
            body = w.get("content") or b""
            if w.get("status") == "success" and isinstance(body, bytes) and body[:4] == b"%PDF":
                text = pdf_to_text(body)
                if len(text) >= 100:
                    return {
                        "status": "success",
                        "text": text,
                        "content": body,
                        "method": "wayback_pdf_ts",
                        "source_url": w.get("url") or url,
                        "error": "",
                    }
                body_for_ocr = body
            else:
                got["error"] = (got.get("error") or "") + f";wb_ts:{w.get('error')}"
        except Exception as exc:
            got["error"] = (got.get("error") or "") + f";wb_ts:{exc}"

    if not allow_ocr:
        return got
    body = body_for_ocr if isinstance(body_for_ocr, bytes) else b""
    if not (body and body[:4] == b"%PDF"):
        try:
            r = live_get(url, ua=UA, verify=False, timeout=(20, 90), retries=2)
            body = r.content or b""
        except Exception as exc:
            got["error"] = (got.get("error") or "") + f";ocr_dl:{exc}"
            return got
    if not (isinstance(body, bytes) and body[:4] == b"%PDF"):
        return got
    max_ocr_bytes = env_int("MAX_OCR_BYTES", 8 * 1024 * 1024)
    if len(body) > max_ocr_bytes:
        got["error"] = (got.get("error") or "") + f";ocr_skip_too_large:{len(body)}"
        return got
    text = pdf_to_text(body)
    if len(re.sub(r"[\x0c\s]+", "", text or "")) >= 100:
        got.update(status="success", text=text, content=body, method=got.get("method") or "http_pdf")
        return got
    log.info("OCR fra %s bytes=%s", url.split("/")[-1][:60], len(body))
    ocr = ocr_pdf(body)
    if len(ocr) >= 100:
        got.update(status="success", text=ocr, content=body, method="http_pdf_ocr_fra")
        return got
    got["error"] = (got.get("error") or "") + ";ocr_short"
    return got


def _live_html(url: str) -> str:
    try:
        r = live_get(url, ua=UA, verify=False, timeout=(15, 60), retries=2)
        if getattr(r, "status_code", 0) != 200:
            return ""
        return r.text or ""
    except Exception as exc:
        log.info("live_html fail %s: %s", url, exc)
        return ""


def discover_direct_pdf_pages(items, seen, pages, portal: str):
    n0 = len(items)
    for page in pages:
        body = _live_html(page)
        if not body:
            continue
        for href in re.findall(r'href=["\']([^"\']+\.pdf[^"\']*)["\']', body, re.I):
            pdf = urljoin(page, html_lib.unescape(href).split("#")[0])
            _add(
                items,
                seen,
                _ident_from_url(pdf),
                pdf,
                {"portal": portal, "title": _title_from_url(pdf), "page_url": page},
            )
        for href in re.findall(r'(https?://[^"\'\s<>]+\.pdf)', body, re.I):
            _add(
                items,
                seen,
                _ident_from_url(href),
                href,
                {"portal": portal, "title": _title_from_url(href), "page_url": page},
            )
    log.info("%s live new=%s catalog=%s", portal, len(items) - n0, len(items))


def discover_finances_images(items, seen):
    """Live PDF directory listings under finances.gouv.ne/images/ (+ HTML pages)."""
    n0 = len(items)
    # Apache directory listings are live and rich (Textes ~70 PDFs; decrets/aje)
    pages = [
        f"{FINANCES}/images/Textes/",
        f"{FINANCES}/images/decrets/",
        f"{FINANCES}/images/decrets/aje/",
        f"{FINANCES}/",
        f"{FINANCES}/index.php/lois-de-finances",
        f"{FINANCES}/index.php/budget-1/reglementations-budgetaires/textes-portant-elaboration",
    ]
    discover_direct_pdf_pages(items, seen, pages, "finances.gouv.ne_images")
    log.info("finances images live pass catalog=%s (+%s)", len(items), len(items) - n0)


def discover_finances_phoca(items, seen):
    """Crawl finances.gouv.ne PhocaDownload categories + shelf pages."""
    if env_int("SKIP_PHOCA", 0):
        return
    n0 = len(items)
    cats = set()
    # Seed shelf pages that already list /file/ links
    shelves = list(FINANCE_INDEXES)
    for url in FINANCE_INDEXES:
        body = _live_html(url)
        if not body:
            continue
        for href in re.findall(r'href=["\']([^"\']+)["\']', body, re.I):
            full = urljoin(url, html_lib.unescape(href)).split("?")[0]
            if "finances.gouv.ne" not in full:
                continue
            if "/category/" in full:
                cats.add(full)
            if "/file/" in full:
                title = _title_from_url(full)
                _add(
                    items,
                    seen,
                    _ident_from_url(full),
                    full,
                    {"portal": "finances.gouv.ne_phoca", "title": title, "phoca": True, "page_url": url},
                )
        time.sleep(0.15)

    def cat_rank(u: str) -> tuple:
        m = re.search(r"(20\d{2}|19\d{2})", u)
        year = int(m.group(1)) if m else 0
        score = 0
        if "lois-de-finances" in u and "archive" not in u:
            score -= 10_000
        elif "organique" in u:
            score -= 9_000
        elif "lois-de-reglement" in u and "archive" not in u:
            score -= 6_000
        elif "textes-portant" in u or "modalites" in u or "directives" in u:
            score -= 8_000
        score -= year
        return (score, -year, u)

    max_cats = env_int("PHOCA_MAX_CATS", 35)
    to_scan = shelves + sorted(cats, key=cat_rank)[:max_cats]
    for url in to_scan:
        body = _live_html(url)
        if not body:
            continue
        for m in re.finditer(r'<a[^>]+href=["\']([^"\']+/file/[^"\']+)["\'][^>]*>(.*?)</a>', body, re.I | re.S):
            href = urljoin(url, html_lib.unescape(m.group(1))).split("?")[0]
            text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html_lib.unescape(m.group(2)))).strip()
            if text.lower() in ("télécharger", "telecharger", "download"):
                text = ""
            title = text or _title_from_url(href)
            _add(
                items,
                seen,
                _ident_from_url(href),
                href,
                {"portal": "finances.gouv.ne_phoca", "title": title, "phoca": True, "page_url": url},
            )
        time.sleep(0.15)
    log.info("finances phoca new=%s catalog=%s cats=%s", len(items) - n0, len(items), len(cats))


def _cdx_with_retry(prefix: str, limit: int, retries: int = 3) -> list[dict]:
    for attempt in range(1, retries + 1):
        try:
            return (
                cdx_urls(
                    prefix,
                    limit=limit,
                    match_type="prefix",
                    extra_filters=["mimetype:application/pdf", "statuscode:200"],
                )
                or []
            )
        except Exception as exc:
            log.info("cdx retry %s attempt=%s: %s", prefix, attempt, exc)
            time.sleep(min(10, 2 * attempt))
    return []


def discover_official_cdx(items, seen):
    if env_int("SKIP_CDX", 0):
        return
    prefixes = [
        ("www.gouv.ne/images/textes-fondamentaux/", "gouv.ne_cdx"),
        ("gouv.ne/images/textes-fondamentaux/", "gouv.ne_cdx"),
        ("justice.gouv.ne/images/lois/", "justice.gouv.ne_cdx"),
        ("www.justice.gouv.ne/images/lois/", "justice.gouv.ne_cdx"),
        ("justice.gouv.ne/images/2019/", "justice.gouv.ne_cdx"),
        ("finances.gouv.ne/images/decrets/", "finances.gouv.ne_cdx"),
        ("www.finances.gouv.ne/images/decrets/", "finances.gouv.ne_cdx"),
        ("finances.gouv.ne/images/Textes/", "finances.gouv.ne_cdx"),
        ("finances.gouv.ne/images/Lois/", "finances.gouv.ne_cdx"),
        ("finances.gouv.ne/images/lois/", "finances.gouv.ne_cdx"),
        ("interieur.gouv.ne/wp-content/uploads/", "interieur.gouv.ne_cdx"),
        ("www.interieur.gouv.ne/wp-content/uploads/", "interieur.gouv.ne_cdx"),
        ("mines.gouv.ne/", "mines.gouv.ne_cdx"),
        ("assemblee.ne/", "assemblee.ne_cdx"),
        ("www.assemblee.ne/", "assemblee.ne_cdx"),
        ("finances.gouv.ne/images/Textes/", "finances.gouv.ne_cdx"),
        ("www.finances.gouv.ne/images/Textes/", "finances.gouv.ne_cdx"),
    ]
    limit = env_int("CDX_LIMIT", 80)
    n0 = len(items)
    digests = set()
    for prefix, portal in prefixes:
        hits = _cdx_with_retry(prefix, limit=limit)
        log.info("cdx %s hits=%s", prefix, len(hits))
        for h in hits:
            orig = (h.get("original") or "").strip()
            if not orig or ".pdf" not in orig.lower():
                continue
            dig = h.get("digest") or ""
            key = dig or _norm_url(orig)
            if key in digests:
                continue
            digests.add(key)
            try:
                length = int(h.get("length") or 0)
            except Exception:
                length = 0
            if length and length > MAX_PDF_BYTES:
                continue
            name = unquote(Path(urlparse(orig).path).name)
            if not _keep_name(orig, name):
                continue
            _add(
                items,
                seen,
                _ident_from_url(orig),
                orig,
                {
                    "portal": portal,
                    "title": _title_from_url(orig),
                    "wayback_ts": h.get("timestamp"),
                    "cdx_length": length,
                },
            )
    log.info("cdx new=%s catalog=%s", len(items) - n0, len(items))


def discover():
    items, seen = [], set()
    discover_direct_pdf_pages(items, seen, GOUV_PAGES, "gouv.ne_textes")
    discover_direct_pdf_pages(items, seen, JUSTICE_PAGES, "justice.gouv.ne")
    discover_direct_pdf_pages(items, seen, INTERIEUR_PAGES, "interieur.gouv.ne")
    discover_finances_images(items, seen)
    discover_finances_phoca(items, seen)
    discover_official_cdx(items, seen)

    def rank(it):
        ident, url, meta = it
        portal = meta.get("portal") or ""
        path = unquote(urlparse(url).path).lower()
        title = (meta.get("title") or "").lower()
        score = 0
        if "gouv.ne_textes" in portal or "constitution" in path or "constitution" in title:
            score -= 50_000
        elif "justice.gouv.ne" in portal and "cdx" not in portal:
            score -= 40_000
        elif "organique" in title or "organique" in path:
            score -= 35_000
        elif "phoca" in portal and re.search(r"(ordonnance|loi-n|loi_n|portant.?loi)", title + path):
            score -= 30_000
        elif "phoca" in portal and re.search(r"(josp|cahier|lf[-_ ]?\d{4})", title + path):
            score -= 20_000
        elif "phoca" in portal:
            score -= 15_000
        elif "finances.gouv.ne_images" in portal:
            score -= 18_000
        elif "finances.gouv.ne_cdx" in portal:
            score -= 12_000
        elif "interieur" in portal:
            score -= 8_000
        elif "cdx" in portal:
            score -= 5_000
        ym = re.search(r"(20\d{2}|19\d{2})", ident + path + title)
        year = int(ym.group(1)) if ym else 0
        score -= year
        length = meta.get("cdx_length") or 0
        if length and length > 4_000_000:
            score += 50
        return (score, -year, url)

    items.sort(key=rank)
    log.info("catalog total=%s", len(items))
    return items


def text_ok(text: str, url: str, title: str | None = None) -> bool:
    if not text or len(text) < 100:
        return False
    if _is_jo(url, title):
        return bool(TEXT_KEEP_RE.search(text[:12000]) or TEXT_KEEP_RE.search(text))
    return bool(TEXT_KEEP_RE.search(text[:6000]) or KEEP_RE.search(unquote(url) + " " + (title or "")))


def _date_from(ident: str, title: str, text: str) -> str | None:
    m2 = re.search(r"(20\d{2}|19\d{2})[-_/ ](\d{1,2})[-_/ ](\d{1,2})", title + " " + ident)
    if m2:
        return f"{m2.group(1)}-{int(m2.group(2)):02d}-{int(m2.group(3)):02d}"
    m3 = re.search(r"\b(20\d{2}|19\d{2})\b", title + " " + ident + " " + text[:400])
    if m3:
        return f"{m3.group(1)}-01-01"
    return None


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 100)
    max_seconds = env_int("MAX_SECONDS", 3600)
    t_start = time.time()
    done = existing_ids(CC)
    ok = skip = fail = 0
    portals: dict[str, int] = {}
    methods: dict[str, int] = {}
    catalog = discover()

    for ident, url, meta in catalog:
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            log.info("MAX_SECONDS reached")
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue

        portal = meta.get("portal") or "unknown"
        title = (meta.get("title") or "").strip()
        wayback_ts = meta.get("wayback_ts")
        phoca = bool(meta.get("phoca")) or ("/file/" in url and "finances.gouv.ne" in url)
        allow_ocr = env_int("OCR_ALL", 0) == 1 or (
            ("jo" in portal or "josp" in (title + url).lower()) and env_int("OCR_JO", 0) == 1
        )

        got = fetch_ne(url, wayback_ts=wayback_ts, allow_ocr=allow_ocr, phoca=phoca)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(
                CC,
                {"identifier": ident, "source_url": url, "reason": got.get("error"), "portal": portal},
            )
            time.sleep(0.4)
            continue
        if not text_ok(text, url, title):
            fail += 1
            log_failure(
                CC,
                {
                    "identifier": ident,
                    "source_url": url,
                    "reason": "filter_no_loi_ordo_decret_const_jo",
                    "portal": portal,
                },
            )
            continue

        if not title or len(title) < 8:
            for ln in text.splitlines():
                s = ln.strip()
                if len(s) > 18 and re.search(
                    r"(?i)\b(journal\s+officiel|loi|constitution|ordonnance|d[eé]cret|code)\b",
                    s,
                ):
                    title = s[:240]
                    break
            if not title or len(title) < 8:
                title = next(
                    (ln.strip()[:240] for ln in text.splitlines() if len(ln.strip()) > 18),
                    title or _title_from_url(url),
                )

        method = got.get("method") or ""
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
            collector="collect_ne.py",
            date=_date_from(ident, title, text),
            article_re=ART,
            extra_meta={
                "fetch_method": method,
                "portal": portal,
                "wayback_ts": wayback_ts,
                "retrieval": "archive" if "wayback" in method else "live",
            },
        ):
            ok += 1
            done.add(rid)
            portals[portal] = portals.get(portal, 0) + 1
            methods[method] = methods.get(method, 0) + 1
            log.info("ok %s portal=%s chars=%s method=%s", ident[:70], portal, len(text), method)
        else:
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "save_failed", "portal": portal})
        time.sleep(0.4)

    write_summary(
        CC,
        country=COUNTRY,
        source="gouv.ne / justice.gouv.ne / finances.gouv.ne / interieur.gouv.ne (Niger)",
        source_urls=[
            f"{GOUV}/index.php/textes-fondamentaux",
            f"{JUSTICE}/index.php/publications/textes-de-lois-et-reglements",
            f"{FINANCES}/index.php/lois-de-finances",
            f"{FINANCES}/index.php/budget-1/reglementations-budgetaires/textes-portant-elaboration",
            f"{INTERIEUR}/documents/",
        ],
        license_text=LICENSE,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage=(
            "catalog-backed incomplete; gouv.ne textes fondamentaux + justice.gouv.ne lois/codes "
            "+ finances.gouv.ne PhocaDownload (LF/JOSP/organiques/décrets) + interieur.gouv.ne décrets; "
            "CDX fills historical /images/decrets and uploads. Niger=ne only (not Nigeria/ng)."
        ),
        notes=(
            f"Official Niger acts only. portals={portals} methods={methods}. "
            "Not AfricanLII. No WAF bypass. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s portals=%s methods=%s", ok, skip, fail, portals, methods)


if __name__ == "__main__":
    main()
