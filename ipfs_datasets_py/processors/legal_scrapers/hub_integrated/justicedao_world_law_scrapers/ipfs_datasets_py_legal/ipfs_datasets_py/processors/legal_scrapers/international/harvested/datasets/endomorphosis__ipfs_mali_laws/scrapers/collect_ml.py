#!/usr/bin/env python3
"""Mali (ml): official Journal Officiel PDFs from SGG + AN/Primature/justice archives.

Official only:
  - https://sgg-mali.ml/fr/journal-officiel/le-journal-officiel.html (JO listing)
  - https://sgg-mali.ml/fr/journal-officiel/les-codes-consolides.html (consolidated codes)
  - https://sgg-mali.ml/fr/journal-officiel/autres-textes-consolides.html (lois/décrets/ordonnances)
  - https://sgg-mali.ml/fr/journal-officiel/journaux-speciaux.html
  - https://sgg-mali.ml/JO/{year}/mali-jo-*.pdf + /codes/ + /autres-textes-consolides/
  - Wayback/CDX of sgg-mali.ml (JO/codes), assemblee-nationale.ml (live 403),
    justice.gouv.ml / primature.gov.ml

Filter: JO fascicules kept; other hosts require loi/ordonnance/décret/constitution/code in name or text.
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

CC, COUNTRY, LANG = "ml", "Mali", "fr"
SOURCE_TYPE = "jo_mali_sgg"
LICENSE = (
    "Secrétariat Général du Gouvernement du Mali (sgg-mali.ml) Journal Officiel / "
    "Assemblée nationale / Primature / justice.gouv.ml. Authentic Journal Officiel / "
    "official text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://sgg-mali.ml/)"
LISTING = "https://sgg-mali.ml/fr/journal-officiel/le-journal-officiel.html"
LISTING_CODES = "https://sgg-mali.ml/fr/journal-officiel/les-codes-consolides.html"
LISTING_AUTRES = "https://sgg-mali.ml/fr/journal-officiel/autres-textes-consolides.html"
LISTING_SP = "https://sgg-mali.ml/fr/journal-officiel/journaux-speciaux.html"
ART = re.compile(r"(?im)^\s*((?:Article|Art\.?)\s+\d+[a-zA-Z]?)\b")
log = logging.getLogger("ml")

ALLOWED_HOST_SUFFIXES = (
    "sgg-mali.ml",
    "assemblee-nationale.ml",
    "primature.gov.ml",
    "primature.gouv.ml",
    "justice.gouv.ml",
    "gouv.ml",
)

PDF_RE = re.compile(
    r'href=["\']([^"\']*JO/\d{4}/mali-jo-[^"\']+\.pdf)["\']',
    re.I,
)
KEEP_RE = re.compile(
    r"(loi|ordonnance|ordonn|d[eé]cret|decret|constitution|code|"
    r"mali-jo|journal.?officiel|\bjo\b|texte)",
    re.I,
)
DROP_RE = re.compile(
    r"(discours|allocution|communique|photo|banner|logo|cv[-_]|biographie|"
    r"rapport[-_ ]annuel|budget[-_ ]citoyen|presentation|organigramme)",
    re.I,
)
TEXT_KEEP_RE = re.compile(
    r"\b(loi|ordonnance|d[eé]cret|decret|constitution|journal\s+officiel|"
    r"code|bulletin des lois|république du mali|republique du mali)\b",
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
        url = "https://" + url[len("http://") :]
    try:
        p = urlsplit(url)
        parts = []
        for seg in p.path.split("/"):
            if not seg:
                parts.append(seg)
                continue
            parts.append(seg if "%" in seg else quote(seg, safe="._-()[]',"))
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
    name = unquote(Path(urlparse(url).path).name)
    stem = Path(name).stem
    m = re.search(r"(mali-jo-.+)$", stem, re.I)
    if m:
        return m.group(1).lower()
    return re.sub(r"\W+", "-", stem).strip("-").lower()[:160] or re.sub(r"\W+", "-", url)[-80:]


def _title_from_url(url: str) -> str:
    name = unquote(Path(urlparse(url).path).name)
    stem = Path(name).stem
    return stem.replace("_", " ").replace("-", " ")[:240] or stem


def _is_jo(url: str) -> bool:
    path = unquote(urlparse(url).path).lower()
    host = (urlparse(url).hostname or "").lower()
    return "sgg-mali.ml" in host and ("/jo/" in path or "mali-jo-" in path)


def _keep_name(url: str, title: str | None = None) -> bool:
    if _is_jo(url):
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
    ident = re.sub(r"\W+", "-", (ident or _ident_from_url(url)).strip("-")).lower()[:160]
    items.append((ident, url, meta or {}))


def ocr_pdf(raw: bytes) -> str:
    """French OCR for image-only official JO scans."""
    max_pages = env_int("MAX_OCR_PAGES", 15)
    dpi = env_int("OCR_DPI", 150)
    try:
        with tempfile.TemporaryDirectory() as td:
            pdf = Path(td) / "doc.pdf"
            pdf.write_bytes(raw)
            proc = subprocess.run(
                [
                    "pdftoppm",
                    "-png",
                    "-r",
                    str(dpi),
                    "-f",
                    "1",
                    "-l",
                    str(max_pages),
                    str(pdf),
                    str(Path(td) / "p"),
                ],
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


def fetch_ml(url: str, *, wayback_ts: str | None = None, allow_ocr: bool = True) -> dict:
    """Live official first; timestamped Wayback of same official URL; OCR scanned PDFs."""
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


def discover_sgg_shelves(items, seen):
    """Consolidated codes + autres textes + journaux spéciaux from SGG shelves."""
    shelves = [
        (LISTING_CODES, "sgg-mali.ml_codes"),
        (LISTING_AUTRES, "sgg-mali.ml_autres"),
        (LISTING_SP, "sgg-mali.ml_speciaux"),
    ]
    for page, portal in shelves:
        n0 = len(items)
        try:
            r = live_get(page, ua=UA, verify=False, timeout=(15, 60), retries=2)
            body = r.text or ""
            if getattr(r, "status_code", 0) != 200:
                raise RuntimeError(f"http_{r.status_code}")
        except Exception as exc:
            log.info("shelf fail %s: %s", page, exc)
            continue
        for href in re.findall(r'href=["\']([^"\']+\.pdf[^"\']*)["\']', body, re.I):
            pdf = urljoin(page, href.split("#")[0])
            if not _host_ok(pdf):
                continue
            # Skip non-law PDFs on shelf pages (communiqués etc.)
            name = unquote(Path(urlparse(pdf).path).name)
            if DROP_RE.search(name):
                continue
            if portal.endswith("_autres") and not KEEP_RE.search(name):
                continue
            _add(
                items,
                seen,
                _ident_from_url(pdf),
                pdf,
                {"portal": portal, "title": _title_from_url(pdf), "page_url": page},
            )
        log.info("shelf %s new=%s catalog=%s", portal, len(items) - n0, len(items))


def discover_jo_listing(items, seen):
    """Primary catalog: SGG JO listing (≈1500 mali-jo PDFs on one page)."""
    n0 = len(items)
    try:
        r = live_get(LISTING, ua=UA, verify=False, timeout=(20, 90), retries=2)
        body = r.text or ""
        if getattr(r, "status_code", 0) != 200:
            raise RuntimeError(f"http_{r.status_code}")
    except Exception as exc:
        log.info("JO listing live fail: %s — trying Wayback", exc)
        got = fetch_official(LISTING, ua=UA, verify=False, min_text=40, wayback=True)
        body = got.get("text") or ""
        if "mali-jo" not in body.lower() and "JO/" not in body:
            # Raw HTML preferred; attempt live_get of known Wayback CDX of listing
            try:
                hits = cdx_urls(
                    "sgg-mali.ml/fr/le-journal-officiel/le-journal-officiel.html",
                    limit=5,
                    match_type="exact",
                    extra_filters=["statuscode:200"],
                )
                if hits:
                    import archive_fallbacks as af

                    w = af.get_wayback_content(
                        _wayback_orig(LISTING),
                        timestamp=hits[0].get("timestamp"),
                    )
                    raw = w.get("content") or b""
                    if isinstance(raw, bytes):
                        body = raw.decode("utf-8", "replace")
            except Exception as exc2:
                log.info("JO listing wayback fail: %s", exc2)
                body = body or ""

    found = 0
    for href in PDF_RE.findall(body):
        pdf = urljoin(LISTING, href.split("#")[0])
        _add(
            items,
            seen,
            _ident_from_url(pdf),
            pdf,
            {"portal": "sgg-mali.ml_jo", "title": f"Journal Officiel — {_ident_from_url(pdf)}"},
        )
        found += 1
    for href in re.findall(
        r"https?://(?:www\.)?sgg-mali\.ml/JO/\d{4}/mali-jo-[^\s\"'<>]+\.pdf",
        body,
        re.I,
    ):
        before = len(seen)
        _add(
            items,
            seen,
            _ident_from_url(href),
            href,
            {"portal": "sgg-mali.ml_jo", "title": f"Journal Officiel — {_ident_from_url(href)}"},
        )
        if len(seen) > before:
            found += 1
    log.info("JO listing new=%s catalog=%s matched=%s", len(items) - n0, len(items), found)


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


def discover_jo_cdx(items, seen):
    """CDX of sgg-mali.ml/JO/ — fills pre-listing years (e.g. 1960s)."""
    if env_int("SKIP_CDX", 0):
        return
    limit = env_int("CDX_JO_LIMIT", 200)
    n0 = len(items)
    digests = set()
    for prefix in ("sgg-mali.ml/JO/", "www.sgg-mali.ml/JO/"):
        hits = _cdx_with_retry(prefix, limit=limit)
        log.info("cdx JO %s hits=%s", prefix, len(hits))
        for h in hits:
            orig = (h.get("original") or "").strip()
            if not orig or "mali-jo-" not in orig.lower() or ".pdf" not in orig.lower():
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
            _add(
                items,
                seen,
                _ident_from_url(orig),
                orig,
                {
                    "portal": "sgg-mali.ml_jo_cdx",
                    "title": f"Journal Officiel — {_ident_from_url(orig)}",
                    "wayback_ts": h.get("timestamp"),
                    "cdx_length": length,
                },
            )
    log.info("JO cdx new=%s catalog=%s", len(items) - n0, len(items))


def discover_official_cdx(items, seen):
    """CDX of AN / justice / Primature — live AN 403, Primature DNS dead."""
    if env_int("SKIP_CDX", 0):
        return
    prefixes = [
        "sgg-mali.ml/codes/",
        "www.sgg-mali.ml/codes/",
        "sgg-mali.ml/autres-textes-consolides/",
        "www.sgg-mali.ml/autres-textes-consolides/",
        "assemblee-nationale.ml/uploads/",
        "www.assemblee-nationale.ml/uploads/",
        "justice.gouv.ml/",
        "www.justice.gouv.ml/",
        "primature.gov.ml/dmdocuments/",
        "www.primature.gov.ml/dmdocuments/",
        "primature.gov.ml/docs_a_telecharger/",
        "www.primature.gov.ml/docs_a_telecharger/",
    ]
    limit = env_int("CDX_LIMIT", 80)
    n0 = len(items)
    for prefix in prefixes:
        hits = _cdx_with_retry(prefix, limit=limit)
        log.info("cdx %s hits=%s", prefix, len(hits))
        for h in hits:
            orig = (h.get("original") or "").strip()
            if not orig or ".pdf" not in orig.lower():
                continue
            name = unquote(Path(urlparse(orig).path).name)
            host = (urlparse(orig).hostname or "").lower()
            # AN uploads have opaque names — keep and filter on text after fetch
            if "sgg-mali.ml" in host and "/codes/" in orig.lower():
                portal = "sgg-mali.ml_codes_cdx"
            elif "sgg-mali.ml" in host and "autres-textes" in orig.lower():
                portal = "sgg-mali.ml_autres_cdx"
            elif "assemblee-nationale.ml" in host:
                portal = "assemblee-nationale.ml_cdx"
            elif "justice.gouv.ml" in host:
                if not KEEP_RE.search(name) and not KEEP_RE.search(orig):
                    continue
                portal = "justice.gouv.ml_cdx"
            elif "primature" in host:
                if not KEEP_RE.search(name) and not KEEP_RE.search(orig):
                    continue
                portal = "primature.gov.ml_cdx"
            else:
                continue
            if DROP_RE.search(name):
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
                },
            )
    log.info("other cdx new=%s catalog=%s", len(items) - n0, len(items))


def discover():
    items, seen = [], set()
    discover_sgg_shelves(items, seen)
    discover_jo_listing(items, seen)
    discover_jo_cdx(items, seen)
    discover_official_cdx(items, seen)

    def rank(it):
        ident, url, meta = it
        portal = meta.get("portal") or ""
        path = unquote(urlparse(url).path).lower()
        # Prefer recent JO from live listing (ident mali-jo-YYYY-…)
        ym = re.search(r"mali-jo-(\d{4})", ident)
        year = int(ym.group(1)) if ym else 0
        # Base portal priority (must dominate year so codes beat recent JO)
        score = 0
        if "sgg-mali.ml_codes" in portal:
            score -= 50_000
        elif "sgg-mali.ml_autres" in portal:
            score -= 40_000
        elif "constitution" in path or "constitution" in (meta.get("title") or "").lower():
            score -= 35_000
        elif "sgg-mali.ml_speciaux" in portal:
            score -= 20_000
        elif portal == "sgg-mali.ml_jo":
            score -= 10_000
        elif "sgg-mali.ml_jo_cdx" in portal:
            score -= 5_000
        elif "justice" in portal:
            score -= 80
        elif "assemblee" in portal:
            score -= 60
        elif "primature" in portal:
            score -= 40
        # Within portal, prefer newer years
        score -= year
        # Prefer smaller CDX lengths (text PDFs) over huge scans when known
        length = meta.get("cdx_length") or 0
        if length and length > 4_000_000:
            score += 50
        return (score, -year, url)

    items.sort(key=rank)
    log.info("catalog total=%s", len(items))
    return items


def text_ok(text: str, url: str) -> bool:
    if not text or len(text) < 100:
        return False
    if _is_jo(url):
        return bool(TEXT_KEEP_RE.search(text[:12000]) or TEXT_KEEP_RE.search(text))
    return bool(TEXT_KEEP_RE.search(text[:6000]) or KEEP_RE.search(unquote(url)))


def _date_from(ident: str, title: str, text: str) -> str | None:
    m = re.search(r"mali-jo-(\d{4})-(\d{1,2})", ident, re.I)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-01"
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
        # OCR mainly for older JO scans / AN; skip by default for large CDX
        allow_ocr = env_int("OCR_ALL", 0) == 1 or (
            "jo" in portal and env_int("OCR_JO", 0) == 1
        )

        got = fetch_ml(url, wayback_ts=wayback_ts, allow_ocr=allow_ocr)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(
                CC,
                {"identifier": ident, "source_url": url, "reason": got.get("error"), "portal": portal},
            )
            time.sleep(0.35)
            continue
        if not text_ok(text, url):
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

        if not title or title.startswith("Journal Officiel — "):
            for ln in text.splitlines():
                s = ln.strip()
                if len(s) > 18 and re.search(
                    r"(?i)\b(journal\s+officiel|loi|constitution|ordonnance|d[eé]cret|code)\b",
                    s,
                ):
                    title = s[:240]
                    break
            if not title or title.startswith("Journal Officiel — "):
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
            collector="collect_ml.py",
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
        time.sleep(0.35)

    write_summary(
        CC,
        country=COUNTRY,
        source="SGG Mali Journal Officiel / Assemblée nationale / Primature / justice.gouv.ml",
        source_urls=[
            LISTING,
            LISTING_CODES,
            LISTING_AUTRES,
            LISTING_SP,
            "https://sgg-mali.ml/JO/",
            "https://sgg-mali.ml/codes/",
            "https://www.assemblee-nationale.ml/",
            "https://justice.gouv.ml/",
            "https://primature.gov.ml/",
        ],
        license_text=LICENSE,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage=(
            "catalog-backed incomplete; sgg-mali.ml JO listing (~1500 mali-jo PDFs 1997–2026) "
            "primary; CDX fills older JO + AN (live 403) + justice/primature. "
            "Older JO scans may need OCR (OCR_JO=1)."
        ),
        notes=(
            f"Official Mali acts only. portals={portals} methods={methods}. "
            "Not AfricanLII. No WAF bypass. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s portals=%s methods=%s", ok, skip, fail, portals, methods)


if __name__ == "__main__":
    main()
