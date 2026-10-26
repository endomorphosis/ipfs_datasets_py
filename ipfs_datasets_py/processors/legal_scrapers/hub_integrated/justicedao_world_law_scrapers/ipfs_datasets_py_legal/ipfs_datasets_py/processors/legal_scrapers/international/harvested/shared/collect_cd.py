#!/usr/bin/env python3
"""DRC / RDC (cd): official laws from Journal Officiel, Présidence, Primature, Parlement, Justice.

Official only:
  - journalofficiel.cd (JO RDC) — live often 503; CDX + timestamped Wayback of same hosts
  - presidence.cd — textes fondateurs / constitutions / ordonnances (live PDFs)
  - primature.cd → primature.gouv.cd — ordonnances / décrets / lois PDFs
  - senat.cd / assemblee-nationale.cd — constitution & lois PDFs (CDX when DNS/live fails)
  - justice.gouv.cd / cour-constitutionnelle.cd — constitution (lois filter)
  - other official *.gouv.cd / *.cd government hosts for loi/ordonnance/décret/constitution PDFs

Filter: loi / ordonnance / décret / constitution (JO uploads_jo fascicules kept when text matches).
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
from urllib.parse import unquote, urljoin, urlparse, quote, urlsplit, urlunsplit

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

CC, COUNTRY, LANG = "cd", "Democratic Republic of the Congo", "fr"
SOURCE_TYPE = "jo_rdc_official"
LICENSE = (
    "Journal Officiel de la République Démocratique du Congo (journalofficiel.cd) / "
    "Présidence (presidence.cd) / Primature (primature.gouv.cd) / Sénat / Assemblée "
    "nationale / justice.gouv.cd / Cour constitutionnelle. Authentic JO / official text "
    "prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://journalofficiel.cd/)"
ART = re.compile(r"(?im)^\s*((?:Article|Art\.)\s+\d+[a-zA-Zº°]?)\b")
log = logging.getLogger("cd")

PRESIDENCE = "https://presidence.cd"
PRIMATURE = "https://www.primature.gouv.cd"
BUDGET = "https://budget.gouv.cd"
DGI = "https://dgi.gouv.cd"
JO_HOSTS = ("journalofficiel.cd", "www.journalofficiel.cd")

ALLOWED_HOST_SUFFIXES = (
    "journalofficiel.cd",
    "presidence.cd",
    "primature.cd",
    "primature.gouv.cd",
    "senat.cd",
    "assemblee-nationale.cd",
    "justice.gouv.cd",
    "cour-constitutionnelle.cd",
    "dgi.gouv.cd",
    "budget.gouv.cd",
    "finances.gouv.cd",
    "gouv.cd",
)

KEEP_RE = re.compile(
    r"(loi|ordonnance|ordonn|d[eé]cret|decret|constitution|code|"
    r"uploads_jo|journal.?officiel|\bjo\b|texte.?fondateur|loi[_-]|ord[_ ]?n|lofip|finances|marches.?publics)",
    re.I,
)
DROP_RE = re.compile(
    r"(discours|allocution|communique|compte[-_ ]?rendu|bio[-_ ]?pr|"
    r"photo|banner|logo|nomination[-_ ]pm|nomination[-_ ]des[-_ ]membres|"
    r"arrete[-_ ]certifie|arret[-_ ]certifie|rconst|rapport[_-]projet|"
    r"rapport[-_ ]annuel|budget[-_ ]citoyen|draft[-_ ]budget|cbmt|"
    r"liste[-_ ]actualisee|transmission[-_ ]liste)",
    re.I,
)
TEXT_KEEP_RE = re.compile(
    r"\b(loi|ordonnance|d[eé]cret|decret|constitution|bulletin des lois|"
    r"journal\s+officiel|lofip|finances|march[eé]s publics)\b",
    re.I,
)

MAX_PDF_BYTES = 25 * 1024 * 1024


def _host_ok(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return any(host == s or host.endswith("." + s) for s in ALLOWED_HOST_SUFFIXES)


def _norm_url(url: str) -> str:
    if not url:
        return ""
    url = html_lib.unescape(url.strip())
    url = url.replace(":80/", "/").replace(":80?", "?")
    if url.startswith("http://"):
        # Prefer https for live official hosts; JO live often 503 anyway
        url = "https://" + url[len("http://") :]
    # Encode path segments with spaces / diacritics for live fetch
    try:
        p = urlsplit(url)
        parts = []
        for seg in p.path.split("/"):
            if not seg:
                parts.append(seg)
                continue
            parts.append(seg if "%" in seg else quote(seg, safe="._-()[]',"))
        url = urlunsplit((p.scheme or "https", p.netloc, "/".join(parts), p.query, ""))
    except Exception:
        url = url.replace(" ", "%20")
    return url


def _wayback_orig(url: str) -> str:
    """HTTP original URL without :80 — Wayback /2id_ needs this; timestamped fetch prefers it."""
    u = html_lib.unescape((url or "").strip())
    u = u.replace(":80/", "/").replace(":80?", "?")
    if u.startswith("https://"):
        u = "http://" + u[len("https://") :]
    return u


def _ident_from_url(url: str) -> str:
    name = unquote(Path(urlparse(url).path).name)
    stem = Path(name).stem
    return re.sub(r"\W+", "-", stem).strip("-")[:160] or re.sub(r"\W+", "-", url)[-80:]


def _title_from_url(url: str) -> str:
    name = unquote(Path(urlparse(url).path).name)
    stem = Path(name).stem
    return stem.replace("_", " ").replace("-", " ")[:240] or stem


def _is_jo_upload(url: str) -> bool:
    path = unquote(urlparse(url).path).lower()
    host = (urlparse(url).hostname or "").lower()
    return "journalofficiel.cd" in host and ("uploads_jo" in path or "/adm/" in path)


def _keep_name(url: str, title: str | None = None) -> bool:
    if _is_jo_upload(url):
        return True
    blob = unquote(urlparse(url).path) + " " + (title or "")
    if DROP_RE.search(blob):
        return False
    return bool(KEEP_RE.search(blob))


def _add(items, seen, ident, url, meta=None):
    url = _norm_url(url)
    if not url or not _host_ok(url):
        return
    if ".pdf" not in url.lower():
        return
    if url in seen:
        return
    title = (meta or {}).get("title")
    if not _keep_name(url, title):
        return
    seen.add(url)
    ident = re.sub(r"\W+", "-", (ident or _ident_from_url(url)).strip("-"))[:160]
    items.append((ident, url, meta or {}))


def ocr_pdf(raw: bytes) -> str:
    """French OCR for image-only official PDFs."""
    max_pages = env_int("MAX_OCR_PAGES", 20)
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


def fetch_cd(url: str, *, wayback_ts: str | None = None, allow_ocr: bool = True) -> dict:
    """Live official first; timestamped Wayback of same official URL; OCR scanned PDFs."""
    got = fetch_official(url, ua=UA, verify=False, min_text=100, wayback=True, wayback_ts=wayback_ts)
    if got.get("status") == "success":
        return got
    # Explicit timestamped Wayback with http original (JO /2id_ without ts → 302)
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
                body_for_ocr = body if isinstance(body, bytes) else b""
                got["error"] = (got.get("error") or "") + f";wb_ts:{w.get('error')}"
        except Exception as exc:
            body_for_ocr = b""
            got["error"] = (got.get("error") or "") + f";wb_ts:{exc}"
    else:
        body_for_ocr = got.get("content") or b""

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
    if len(body) > env_int("MAX_OCR_BYTES", 10 * 1024 * 1024):
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


def _extract_pdfs(html_text: str, base: str) -> list[tuple[str, str | None]]:
    out = []
    soup_titles = {}
    for m in re.finditer(
        r'<a[^>]+href=["\']([^"\']+\.pdf[^"\']*)["\'][^>]*>(.*?)</a>',
        html_text or "",
        re.I | re.S,
    ):
        href = html_lib.unescape(m.group(1))
        title = re.sub(r"<[^>]+>", " ", m.group(2) or "")
        title = re.sub(r"\s+", " ", title).strip()[:240] or None
        full = urljoin(base, href)
        out.append((full, title))
        soup_titles[full] = title
    for m in re.finditer(r'href=["\']([^"\']+\.pdf[^"\']*)["\']', html_text or "", re.I):
        href = html_lib.unescape(m.group(1))
        full = urljoin(base, href)
        if full not in soup_titles:
            out.append((full, None))
    # absolute
    for m in re.finditer(
        r'https?://(?:[\w.-]+\.)?(?:presidence\.cd|primature\.gouv\.cd|primature\.cd|'
        r'journalofficiel\.cd|senat\.cd|assemblee-nationale\.cd|justice\.gouv\.cd|'
        r'cour-constitutionnelle\.cd)[^"\'\s<>]*?\.pdf',
        html_text or "",
        re.I,
    ):
        out.append((m.group(0), None))
    dedup = []
    seen = set()
    for u, t in out:
        nu = _norm_url(u)
        if nu and nu not in seen:
            seen.add(nu)
            dedup.append((nu, t))
    return dedup


def discover_presidence(items, seen):
    seeds = [
        f"{PRESIDENCE}/ressources/constitutions",
        f"{PRESIDENCE}/ressources/ordonnances",
        f"{PRESIDENCE}/textes-fondateurs",
        f"{PRESIDENCE}/president/textes-fondateurs",
        f"{PRESIDENCE}/detail-texte-fondateur/1",
        f"{PRESIDENCE}/detail-texte-fondateur/2",
    ]
    for page in range(0, env_int("ORD_PAGES", 6)):
        seeds.append(
            f"{PRESIDENCE}/ressources/ordonnances?page={page}"
            if page
            else f"{PRESIDENCE}/ressources/ordonnances"
        )
    n0 = len(items)
    for seed in seeds:
        try:
            r = live_get(seed, ua=UA, verify=False, timeout=(12, 40), retries=2)
        except Exception as exc:
            log.info("presidence fail %s: %s", seed[:70], exc)
            continue
        if getattr(r, "status_code", 0) != 200:
            continue
        for url, title in _extract_pdfs(r.text or "", r.url):
            portal = "presidence.cd"
            low = (title or "") + " " + unquote(urlparse(url).path)
            if "constitution" in low.lower() or "texte" in seed:
                portal = "presidence.cd_constitution" if "constitution" in low.lower() else portal
            if "ordonn" in low.lower() or "ordonnances" in seed:
                portal = "presidence.cd_ordonnance"
            _add(items, seen, _ident_from_url(url), url, {"portal": portal, "title": title or _title_from_url(url)})
    log.info("presidence new=%s catalog=%s", len(items) - n0, len(items))


def discover_primature_live(items, seen):
    seeds = [
        f"{PRIMATURE}/",
        f"{PRIMATURE}/?s=ordonnance",
        f"{PRIMATURE}/?s=loi",
        f"{PRIMATURE}/?s=decret",
        f"{PRIMATURE}/?s=constitution",
    ]
    n0 = len(items)
    for seed in seeds:
        try:
            r = live_get(seed, ua=UA, verify=False, timeout=(12, 40), retries=1)
        except Exception as exc:
            log.info("primature fail %s: %s", seed[:70], exc)
            continue
        if getattr(r, "status_code", 0) != 200:
            continue
        for url, title in _extract_pdfs(r.text or "", r.url):
            _add(
                items,
                seen,
                _ident_from_url(url),
                url,
                {"portal": "primature.gouv.cd", "title": title or _title_from_url(url)},
            )
    log.info("primature live new=%s", len(items) - n0)



def discover_budget_live(items, seen):
    seeds = [
        f"{BUDGET}/",
        f"{BUDGET}/lois-de-finances/",
        f"{BUDGET}/?s=loi",
        f"{BUDGET}/?s=lofip",
        f"{BUDGET}/?s=ordonnance",
        f"{BUDGET}/?s=decret",
        "https://www.budget.gouv.cd/lois-de-finances/",
    ]
    n0 = len(items)
    for seed in seeds:
        try:
            r = live_get(seed, ua=UA, verify=False, timeout=(12, 40), retries=1)
        except Exception as exc:
            log.info("budget fail %s: %s", seed[:70], exc)
            continue
        if getattr(r, "status_code", 0) != 200:
            continue
        for url, title in _extract_pdfs(r.text or "", r.url):
            _add(
                items,
                seen,
                _ident_from_url(url),
                url,
                {"portal": "budget.gouv.cd", "title": title or _title_from_url(url)},
            )
    log.info("budget live new=%s", len(items) - n0)


def discover_dgi_live(items, seen):
    seeds = [
        f"{DGI}/",
        f"{DGI}/code-des-impots/",
        f"{DGI}/?s=loi",
        f"{DGI}/?s=code",
        f"{DGI}/?s=ordonnance",
        f"{DGI}/?s=decret",
    ]
    n0 = len(items)
    for seed in seeds:
        try:
            r = live_get(seed, ua=UA, verify=False, timeout=(12, 40), retries=1)
        except Exception as exc:
            log.info("dgi fail %s: %s", seed[:70], exc)
            continue
        if getattr(r, "status_code", 0) != 200:
            continue
        for url, title in _extract_pdfs(r.text or "", r.url):
            _add(
                items,
                seen,
                _ident_from_url(url),
                url,
                {"portal": "dgi.gouv.cd", "title": title or _title_from_url(url)},
            )
    log.info("dgi live new=%s", len(items) - n0)


def discover_jo_cdx(items, seen):
    """CDX of journalofficiel.cd uploads_jo PDFs — carry timestamp for Wayback replay."""
    limit = env_int("CDX_JO_LIMIT", 250)
    prefixes = [
        "journalofficiel.cd/adm/uploads_jo/",
        "www.journalofficiel.cd/adm/uploads_jo/",
        "journalofficiel.cd/jordc/adm/uploads_jo/",
        "www.journalofficiel.cd/jordc/adm/uploads_jo/",
    ]
    n0 = len(items)
    digests = set()
    for prefix in prefixes:
        try:
            hits = cdx_urls(
                prefix,
                limit=limit,
                match_type="prefix",
                extra_filters=["mimetype:application/pdf", "statuscode:200"],
            )
        except Exception as exc:
            log.info("cdx JO fail %s: %s", prefix, exc)
            continue
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
            ts = h.get("timestamp") or None
            url = _norm_url(orig)
            _add(
                items,
                seen,
                _ident_from_url(url),
                url,
                {
                    "portal": "journalofficiel.cd_cdx",
                    "title": f"Journal Officiel RDC {_ident_from_url(url)}",
                    "wayback_ts": ts,
                    "cdx_length": length,
                },
            )
    log.info("JO cdx new=%s catalog=%s", len(items) - n0, len(items))


def discover_official_cdx(items, seen):
    """CDX of other official .cd hosts — loi/ordonnance/décret/constitution filenames."""
    prefixes = [
        "presidence.cd/uploads/files/",
        "www.presidence.cd/uploads/files/",
        "www.primature.gouv.cd/wp-content/uploads/",
        "primature.gouv.cd/wp-content/uploads/",
        "senat.cd/",
        "www.senat.cd/",
        "assemblee-nationale.cd/",
        "www.assemblee-nationale.cd/",
        "cour-constitutionnelle.cd/wp-content/uploads/",
        "www.cour-constitutionnelle.cd/wp-content/uploads/",
        "justice.gouv.cd/wp-content/uploads/",
        "budget.gouv.cd/wp-content/uploads/",
        "www.budget.gouv.cd/wp-content/uploads/",
        "dgi.gouv.cd/wp-content/uploads/",
        "www.dgi.gouv.cd/wp-content/uploads/",
    ]
    limit = env_int("CDX_LIMIT", 120)
    n0 = len(items)
    for prefix in prefixes:
        try:
            hits = cdx_urls(
                prefix,
                limit=limit,
                match_type="prefix",
                extra_filters=["mimetype:application/pdf", "statuscode:200"],
            )
        except Exception as exc:
            log.info("cdx fail %s: %s", prefix, exc)
            continue
        for h in hits:
            orig = (h.get("original") or "").strip()
            if not orig or ".pdf" not in orig.lower():
                continue
            name = unquote(Path(urlparse(orig).path).name)
            if DROP_RE.search(name):
                continue
            if not KEEP_RE.search(name) and not KEEP_RE.search(orig):
                continue
            url = _norm_url(orig)
            host = (urlparse(url).hostname or "").lower()
            portal = f"cdx:{host}"
            _add(
                items,
                seen,
                _ident_from_url(url),
                url,
                {
                    "portal": portal,
                    "title": _title_from_url(url),
                    "wayback_ts": h.get("timestamp"),
                },
            )
    log.info("other cdx new=%s catalog=%s", len(items) - n0, len(items))


def discover():
    items, seen = [], set()
    # 1) Live Présidence (working constitutions + ordonnances)
    discover_presidence(items, seen)
    # 2) Live Primature / Budget / DGI (official .gouv.cd)
    discover_primature_live(items, seen)
    discover_budget_live(items, seen)
    discover_dgi_live(items, seen)
    # 3) JO CDX (primary gazette corpus; live often 503)
    discover_jo_cdx(items, seen)
    # 4) Other official CDX
    if len(items) < env_int("CATALOG_MIN", 100):
        discover_official_cdx(items, seen)
    else:
        discover_official_cdx(items, seen)

    def rank(it):
        url, meta = it[1], it[2] or {}
        portal = meta.get("portal") or ""
        path = unquote(urlparse(url).path).lower()
        if "constitution" in path or "constitution" in portal:
            return 0
        if "presidence.cd_ordonnance" in portal or "ordonn" in path:
            return 1
        if "presidence" in portal:
            return 2
        if "journalofficiel" in portal:
            return 3
        if "primature" in portal:
            return 4
        return 5

    items.sort(key=rank)
    log.info("catalog total=%s", len(items))
    return items


def text_ok(text: str, url: str) -> bool:
    if not text or len(text) < 100:
        return False
    if _is_jo_upload(url):
        return bool(TEXT_KEEP_RE.search(text[:8000]) or TEXT_KEEP_RE.search(text))
    return bool(TEXT_KEEP_RE.search(text[:4000]) or KEEP_RE.search(unquote(url)))


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 80)
    max_seconds = env_int("MAX_SECONDS", 3600)
    t_start = time.time()
    done = existing_ids(CC)
    ok = skip = fail = 0
    portals: dict[str, int] = {}
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

        got = fetch_cd(url, wayback_ts=wayback_ts)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(
                CC,
                {"identifier": ident, "source_url": url, "reason": got.get("error"), "portal": portal},
            )
            continue
        if not text_ok(text, url):
            fail += 1
            log_failure(
                CC,
                {"identifier": ident, "source_url": url, "reason": "filter_no_loi_ordo_decret_const", "portal": portal},
            )
            continue

        if not title or title.startswith("Journal Officiel RDC "):
            title = next(
                (ln.strip()[:240] for ln in text.splitlines() if len(ln.strip()) > 18),
                title or _title_from_url(url),
            )

        date = None
        m = re.search(r"(20\d{2}|19\d{2})[-_/ ](\d{1,2})[-_/ ](\d{1,2})", title + " " + ident)
        if m:
            date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        else:
            m2 = re.search(r"\b(20\d{2}|19\d{2})\b", title + " " + ident + " " + text[:500])
            if m2:
                date = f"{m2.group(1)}-01-01"

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
            collector="collect_cd.py",
            date=date,
            article_re=ART,
            extra_meta={
                "fetch_method": got.get("method"),
                "portal": portal,
                "wayback_ts": wayback_ts,
            },
        ):
            ok += 1
            done.add(rid)
            portals[portal] = portals.get(portal, 0) + 1
            log.info("ok %s portal=%s chars=%s method=%s", ident[:70], portal, len(text), got.get("method"))
        else:
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "save_failed", "portal": portal})

    write_summary(
        CC,
        country=COUNTRY,
        source="Journal Officiel RDC / Présidence / Primature / Parlement / Justice (.cd)",
        source_urls=[
            "https://journalofficiel.cd/",
            "https://presidence.cd/ressources/constitutions",
            "https://presidence.cd/ressources/ordonnances",
            "https://www.primature.gouv.cd/",
            "https://www.senat.cd/",
            "https://cour-constitutionnelle.cd/",
            "https://justice.gouv.cd/",
            "https://budget.gouv.cd/lois-de-finances/",
            "https://dgi.gouv.cd/",
        ],
        license_text=LICENSE,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage=(
            "catalog-backed incomplete; journalofficiel.cd live HTTP 503 from collector host — "
            "CDX+timestamped Wayback of official JO uploads_jo; live Présidence constitutions/ordonnances primary"
        ),
        notes=f"Official DRC/RDC acts only. portals={portals}. Not AfricanLII/Droit-Afrique. No WAF bypass. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s portals=%s", ok, skip, fail, portals)


if __name__ == "__main__":
    main()
