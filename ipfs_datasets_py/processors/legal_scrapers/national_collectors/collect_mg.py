#!/usr/bin/env python3
"""Madagascar (mg): official laws from CNLEGIS / Trésor / Assemblée / Primature / MEF / CENI.

Official only:
  - https://cnlegis.gov.mg/uploads/ (DIRCNLEGIS / SGG / Primature — JO texts L/D/O/A)
  - https://app.primature.gov.mg/gouvernement/decrets (links to cnlegis PDFs)
  - http://www.tresorpublic.mg/ (Trésor Public — lois / décrets download.php)
  - https://www.assemblee-nationale.mg/ (lois + Constitution via wp-content CDX;
    live textes on official AN Cloudflare R2 CDN)
  - https://www.ceni-madagascar.mg/ (organic electoral laws)
  - https://www.hcc.gov.mg/ / https://www.primature.gov.mg/ / https://www.mef.gov.mg/
  - Wayback/CDX of the same official *.gov.mg / assemblee-nationale.mg / tresorpublic.mg /
    cnlegis.gov.mg / ceni-madagascar.mg URLs

Filter: loi/ordonnance/décret/constitution/code; drop CV/agenda/newsletter/guide/projet.
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
from urllib.parse import unquote, urljoin, urlparse, quote, urlsplit, urlunsplit, parse_qs

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

CC, COUNTRY, LANG = "mg", "Madagascar", "fr"
SOURCE_TYPE = "madagascar_official_lois"
LICENSE = (
    "République de Madagascar — DIRCNLEGIS / SGG (cnlegis.gov.mg) / Primature "
    "(primature.gov.mg / app.primature.gov.mg) / Trésor Public (tresorpublic.mg) / "
    "Assemblée nationale (assemblee-nationale.mg) / HCC (hcc.gov.mg) / "
    "MEF (mef.gov.mg) / CENI (ceni-madagascar.mg). "
    "Authentic Journal Officiel / official text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://cnlegis.gov.mg/; Madagascar=mg)"
ART = re.compile(r"(?im)^\s*((?:Article|Art\.?)\s+\d+[a-zA-Zº°]?)\b")
log = logging.getLogger("mg")

CNLEGIS = "https://cnlegis.gov.mg"
AN = "https://www.assemblee-nationale.mg"
HCC = "https://www.hcc.gov.mg"
PRIMATURE = "https://www.primature.gov.mg"
APP_PRIMATURE = "https://app.primature.gov.mg"
MEF = "https://www.mef.gov.mg"
TRESOR = "http://www.tresorpublic.mg"
CENI = "https://www.ceni-madagascar.mg"

# Official AN document CDN (Cloudflare R2) linked from assemblee-nationale.mg
AN_R2_HOST = "pub-7e0d3a35c1b949698a7ced344fa56252.r2.dev"

ALLOWED_HOST_SUFFIXES = (
    "cnlegis.gov.mg",
    "assemblee-nationale.mg",
    "hcc.gov.mg",
    "primature.gov.mg",
    "mef.gov.mg",
    "tresorpublic.mg",
    "ceni-madagascar.mg",
    "presidence.gov.mg",
    "senat.mg",
    "senat.gov.mg",
    "justice.gov.mg",
    "sgg.gov.mg",
    "portal.impots.mg",
    "impots.mg",
    "gouv.mg",
    "gov.mg",
    AN_R2_HOST,
)

KEEP_RE = re.compile(
    r"(loi|ordonnance|ordonn|d[eé]cret|decret|arr[eê]t[eé]|arrete|constitution|code|"
    r"journal.?officiel|\bjosp?\b|\bjo\b|\blf\b|\blfi\b|\blo\b|organique|charte|statut|"
    r"texte.?juridique|texte.?fondament|"
    r"(?:^|/)[LDAO]\d{4}|constitution)",
    re.I,
)
DROP_RE = re.compile(
    r"(discours|allocution|communique|photo|banner|logo|cv[-_]|curriculum|"
    r"biographie|newsletter|rapport[-_ ]|presentation|organigramme|"
    r"agenda|ouverture.?session|guide[-_ ]|manuel|brochure|fiche[-_ ]|"
    r"planning|calendrier|pges|pmo-pge|ceb\d|creb|rdf_|rma-|projet[-_ ]?de[-_ ]?loi|"
    r"projet_de_loi|projet-de-loi|expose[-_ ]?des[-_ ]?motifs|news|"
    r"liste[-_ ]et[-_ ]empl|recap|electeurs|bv[-_])",
    re.I,
)
TEXT_KEEP_RE = re.compile(
    r"\b(loi|ordonnance|d[eé]cret|decret|constitution|journal\s+officiel|"
    r"code|bulletin des lois|r[eé]publique de madagascar|madagascar|"
    r"assembl[eé]e\s+nationale|haute\s+cour\s+constitutionnelle|"
    r"primature|pr[eé]sidence|tr[eé]sor)\b",
    re.I,
)

AN_NUM_RE = re.compile(r"^\d{4}-\d{2,4}(?:_fr)?\.pdf$", re.I)
CNLEGIS_ACT_RE = re.compile(r"^[LDAO]\d{4}", re.I)

MAX_PDF_BYTES = 25 * 1024 * 1024

LIVE_PAGES = [
    f"{CNLEGIS}/",
    f"{APP_PRIMATURE}/gouvernement/decrets",
    f"{AN}/",
    f"{AN}/textes/",
    f"{HCC}/",
    f"{PRIMATURE}/",
    "https://primature.gov.mg/",
    f"{MEF}/",
    f"{CENI}/",
    f"{TRESOR}/?page_id=214&content=temp&type=loi",
]


def _host_ok(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    if not host:
        return False
    if any(x in host for x in ("africanlii", "droit-afrique", "legifrance", "ilo.org")):
        return False
    if host == AN_R2_HOST:
        return True
    return any(host == s or host.endswith("." + s) for s in ALLOWED_HOST_SUFFIXES)


def _norm_url(url: str) -> str:
    if not url:
        return ""
    url = html_lib.unescape(url.strip())
    url = url.replace(":80/", "/").replace(":80?", "?")
    # Keep tresorpublic on http — https often fails; download.php is http-native
    host0 = (urlsplit(url).hostname or "").lower()
    if "tresorpublic.mg" in host0:
        if url.startswith("https://"):
            url = "http://" + url[len("https://") :]
    elif url.startswith("http://"):
        url = "https://" + url[len("http://") :]
    try:
        p = urlsplit(url)
        host = (p.hostname or "").lower()
        if host in ("assemblee-nationale.mg",):
            host = "www.assemblee-nationale.mg"
        elif host in ("hcc.gov.mg",):
            host = "www.hcc.gov.mg"
        elif host in ("cnlegis.gov.mg", "www.cnlegis.gov.mg"):
            host = "cnlegis.gov.mg"
        netloc = host
        if p.port and p.port not in (80, 443):
            netloc = f"{host}:{p.port}"
        parts = []
        for seg in p.path.split("/"):
            if not seg:
                parts.append(seg)
                continue
            parts.append(seg if "%" in seg else quote(seg, safe="._-()[]',°"))
        # Preserve query for tresor download.php
        query = p.query if "tresorpublic.mg" in host else ""
        url = urlunsplit((p.scheme or "https", netloc, "/".join(parts), query, ""))
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
    p = urlparse(url)
    name = unquote(Path(p.path).name)
    if "tresorpublic.mg" in (p.hostname or "").lower() and "download.php" in p.path:
        qs = parse_qs(p.query)
        file_ = (qs.get("file") or [""])[0]
        path_q = (qs.get("path") or [""])[0]
        stem = Path(unquote(file_)).stem or "tresor"
        kind = "loi"
        pl = unquote(path_q).lower()
        if "/decrets/" in pl:
            kind = "decret"
        elif "/arretes/" in pl:
            kind = "arrete"
        return re.sub(r"\W+", "-", f"tresor-{kind}-{stem}").strip("-").lower()[:160]
    stem = Path(name).stem
    return re.sub(r"\W+", "-", stem).strip("-").lower()[:160] or re.sub(r"\W+", "-", url)[-80:]


def _title_from_url(url: str) -> str:
    p = urlparse(url)
    if "tresorpublic.mg" in (p.hostname or "").lower():
        qs = parse_qs(p.query)
        file_ = (qs.get("file") or [""])[0]
        if file_:
            return Path(unquote(file_)).stem.replace("_", " ").replace("-", " ")[:240]
    name = unquote(Path(p.path).name)
    stem = Path(name).stem
    stem = stem.replace("%C2%B0", " ").replace("°", " ")
    return stem.replace("_", " ").replace("-", " ")[:240] or stem


def _is_an_numbered_loi(url: str) -> bool:
    name = unquote(Path(urlparse(url).path).name)
    host = (urlparse(url).hostname or "").lower()
    return "assemblee-nationale.mg" in host and bool(AN_NUM_RE.match(name))


def _is_cnlegis_act(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    name = unquote(Path(urlparse(url).path).name)
    return "cnlegis.gov.mg" in host and (
        bool(CNLEGIS_ACT_RE.match(name)) or "constitution" in name.lower()
    )


def _is_constitution(url: str, title: str | None = None) -> bool:
    blob = unquote(urlparse(url).path) + " " + (title or "")
    return bool(re.search(r"(?i)constitut", blob))


def _keep_name(url: str, title: str | None = None) -> bool:
    if _is_an_numbered_loi(url) or _is_constitution(url, title) or _is_cnlegis_act(url):
        return True
    host = (urlparse(url).hostname or "").lower()
    if "tresorpublic.mg" in host and "download.php" in url:
        path_q = unquote((parse_qs(urlparse(url).query).get("path") or [""])[0]).lower()
        file_ = unquote((parse_qs(urlparse(url).query).get("file") or [""])[0]).lower()
        blob = path_q + " " + file_ + " " + (title or "")
        if DROP_RE.search(blob):
            return False
        return bool(re.search(r"(?i)(/lois/|/decrets/|loi|d[eé]cret|ordonnance|constit)", blob))
    if AN_R2_HOST in host:
        blob = unquote(urlparse(url).path) + " " + (title or "")
        if DROP_RE.search(blob):
            return False
        # Keep Constitution + principal enacted-looking texts; skip exposés / agendas
        if re.search(r"(?i)constitut", blob):
            return True
        if re.search(r"(?i)(PRINCIPAL_FR|/PL[-_]|RESOLUTION|Loi[_-]|Decret|D[eé]cret)", blob):
            return True
        return False
    blob = unquote(urlparse(url).path) + " " + (title or "") + " " + url
    if DROP_RE.search(blob):
        if not KEEP_RE.search(blob):
            return False
        if re.search(
            r"(?i)(cv[-_]|curriculum|newsletter|agenda|projet[-_ ]?de[-_ ]?loi|projet_de_loi|expose)",
            blob,
        ):
            return False
    if ".pdf" not in url.lower() and "download.php" not in url.lower():
        return False
    return bool(KEEP_RE.search(blob))


def _add(items, seen, ident, url, meta=None):
    url = _norm_url(url)
    if not url or not _host_ok(url):
        return
    if ".pdf" not in url.lower() and "download.php" not in url.lower():
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
    max_pages = env_int("MAX_OCR_PAGES", 12)
    dpi = env_int("OCR_DPI", 150)
    try:
        with tempfile.TemporaryDirectory() as td:
            pdf = Path(td) / "doc.pdf"
            pdf.write_bytes(raw)
            proc = subprocess.run(
                [
                    "pdftoppm", "-png", "-r", str(dpi),
                    "-f", "1", "-l", str(max_pages),
                    str(pdf), str(Path(td) / "p"),
                ],
                check=False, capture_output=True, timeout=240,
            )
            if proc.returncode != 0:
                return ""
            chunks = []
            for img in sorted(Path(td).glob("p*.png")):
                tproc = subprocess.run(
                    ["tesseract", str(img), "stdout", "-l", "fra", "--psm", "6"],
                    check=False, capture_output=True, timeout=120,
                )
                if tproc.returncode == 0 and tproc.stdout:
                    chunks.append(tproc.stdout.decode("utf-8", "replace").strip())
            return "\n\n".join(c for c in chunks if c).strip()
    except Exception as exc:
        log.warning("ocr_pdf: %s", exc)
        return ""


def fetch_mg(url: str, *, wayback_ts: str | None = None, allow_ocr: bool = True) -> dict:
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
    if len(body) > MAX_PDF_BYTES:
        got["error"] = (got.get("error") or "") + f";pdf_too_large:{len(body)}"
        return got
    text = pdf_to_text(body)
    if len(re.sub(r"[\x0c\s]+", "", text or "")) >= 100:
        got.update(status="success", text=text, content=body, method=got.get("method") or "http_pdf")
        return got
    if len(body) > env_int("MAX_OCR_BYTES", 8 * 1024 * 1024):
        return got
    ocr = ocr_pdf(body)
    if len(ocr) >= 100:
        return {
            "status": "success",
            "text": ocr,
            "content": body,
            "method": "ocr_fra",
            "source_url": url,
            "error": "",
        }
    return got


def _cdx_with_retry(prefix: str, limit: int = 200, extra_filters=None) -> list:
    for attempt in range(1, 4):
        try:
            return cdx_urls(prefix, limit=limit, extra_filters=extra_filters) or []
        except Exception as exc:
            log.info("cdx retry %s attempt=%s: %s", prefix, attempt, exc)
            time.sleep(min(10, 2 * attempt))
    return []


def discover_cnlegis_cdx(items, seen):
    if env_int("SKIP_CDX", 0):
        return
    limit = env_int("CDX_CNLEGIS_LIMIT", 400)
    n0 = len(items)
    digests = set()
    for prefix in ("cnlegis.gov.mg/uploads/", "www.cnlegis.gov.mg/uploads/"):
        hits = _cdx_with_retry(
            prefix,
            limit=limit,
            extra_filters=["mimetype:application/pdf", "statuscode:200"],
        )
        log.info("cdx cnlegis %s hits=%s", prefix, len(hits))
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
            # Prefer L/O/Constitution; also keep D/A (décrets/arrêtés)
            if not (
                CNLEGIS_ACT_RE.match(name)
                or "constitution" in name.lower()
                or KEEP_RE.search(name)
            ):
                continue
            portal = "cnlegis.gov.mg_cdx"
            if name.upper().startswith("L") or "constitution" in name.lower():
                portal = "cnlegis.gov.mg_loi_cdx"
            elif name.upper().startswith("O"):
                portal = "cnlegis.gov.mg_ordo_cdx"
            elif name.upper().startswith("D"):
                portal = "cnlegis.gov.mg_decret_cdx"
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
    log.info("cnlegis cdx new=%s catalog=%s", len(items) - n0, len(items))

def discover_cnlegis_loi_live(items, seen):
    """Live Range-probe of cnlegis.gov.mg/uploads/L* (soft-404 returns HTML 200).

    Real PDFs start with %PDF; soft-404 is ~38KB text/html. Prefer -VF. Seed file
    mg_cnlegis_lois_seed.txt holds previously validated names; optional pattern
    expansion is capped by CNLEGIS_LOI_PROBE_MAX.
    """
    if env_int("SKIP_CNLEGIS_LOI_PROBE", 0):
        return
    import ssl
    import urllib.request

    n0 = len(items)
    ctx = ssl._create_unverified_context()
    seed_path = Path(__file__).resolve().parent / "mg_cnlegis_lois_seed.txt"
    seeds = []
    if seed_path.is_file():
        seeds = [ln.strip() for ln in seed_path.read_text().splitlines() if ln.strip().endswith(".pdf")]

    cands = list(seeds)
    if env_int("CNLEGIS_LOI_EXPAND", 0) == 1:
        for year in range(env_int("CNLEGIS_LOI_YEAR_FROM", 2018), env_int("CNLEGIS_LOI_YEAR_TO", 2027)):
            for n in range(1, env_int("CNLEGIS_LOI_N_MAX", 45) + 1):
                for fmt in (
                    f"L{year}-{n:03d}-VF.pdf",
                    f"L{year}-{n:03d}.pdf",
                    f"L{year}-{n:03d}(VF).pdf",
                ):
                    cands.append(fmt)
    seen_names: set[str] = set()
    names: list[str] = []
    for c in cands:
        if c not in seen_names:
            seen_names.add(c)
            names.append(c)
    max_probe = env_int("CNLEGIS_LOI_PROBE_MAX", 250)
    names = names[:max_probe]

    def _is_pdf(url: str) -> bool:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Range": "bytes=0-7"})
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=12) as r:
                body = r.read(8)
                ct = (r.headers.get("Content-Type") or "").lower()
                if body.startswith(b"%PDF"):
                    return True
                return "pdf" in ct and not body.lstrip().lower().startswith(b"<!doc")
        except Exception:
            return False

    ok = 0
    for name in names:
        url = f"{CNLEGIS}/uploads/{name}"
        if _norm_url(url).lower() in seen:
            continue
        if not _is_pdf(url):
            continue
        _add(
            items,
            seen,
            _ident_from_url(url),
            url,
            {"portal": "cnlegis.gov.mg_loi_live", "title": _title_from_url(url)},
        )
        ok += 1
        if ok and ok % 25 == 0:
            log.info("cnlegis loi live progress found=%s catalog=%s", ok, len(items))
    log.info("cnlegis loi live new=%s catalog=%s probed=%s", len(items) - n0, len(items), len(names))



def discover_tresor(items, seen):
    n0 = len(items)
    page = f"{TRESOR}/?page_id=214&content=temp&type=loi"
    try:
        r = live_get(page, ua=UA, verify=False, timeout=(20, 90), retries=2)
        html = r.text or ""
        base = str(getattr(r, "url", None) or page)
    except Exception as exc:
        log.info("tresor live fail: %s", exc)
        return
    for m in re.finditer(
        r'<a[^>]+href=["\']([^"\']*download\.php[^"\']*)["\'][^>]*>(.*?)</a>',
        html,
        re.I | re.S,
    ):
        href = html_lib.unescape(m.group(1))
        title = re.sub(r"<[^>]+>", " ", m.group(2))
        title = re.sub(r"\s+", " ", title).strip()[:240]
        full = urljoin(base, href)
        path_q = unquote((parse_qs(urlparse(full).query).get("path") or [""])[0]).lower()
        if "/lois/" in path_q:
            portal = "tresorpublic.mg_lois"
        elif "/decrets/" in path_q:
            portal = "tresorpublic.mg_decrets"
        elif "/arretes/" in path_q:
            portal = "tresorpublic.mg_arretes"
        else:
            continue
        _add(
            items,
            seen,
            _ident_from_url(full),
            full,
            {"portal": portal, "title": title or _title_from_url(full), "page_url": page},
        )
    log.info("tresor new=%s catalog=%s", len(items) - n0, len(items))


def discover_an_textes(items, seen):
    """Live AN /textes/ pages — PDFs on official AN R2 CDN + Constitution archive."""
    n0 = len(items)
    for page_n in range(1, 12):
        page = f"{AN}/textes/" if page_n == 1 else f"{AN}/textes/?page={page_n}"
        try:
            r = live_get(page, ua=UA, verify=False, timeout=(15, 45), retries=1)
            html = r.text or ""
        except Exception as exc:
            log.info("AN textes page fail %s: %s", page_n, exc)
            break
        found = 0
        for href in re.findall(r'href=["\']([^"\']+\.pdf[^"\']*)["\']', html, re.I):
            full = urljoin(page, html_lib.unescape(href))
            before = len(seen)
            _add(
                items,
                seen,
                _ident_from_url(full),
                full,
                {"portal": "assemblee-nationale.mg_textes", "title": _title_from_url(full)},
            )
            if len(seen) > before:
                found += 1
        log.info("AN textes page=%s new=%s", page_n, found)
        if found == 0 and page_n > 3:
            break
    log.info("AN textes new=%s catalog=%s", len(items) - n0, len(items))


def discover_live_pages(items, seen):
    n0 = len(items)
    for page in LIVE_PAGES:
        try:
            r = live_get(page, ua=UA, verify=False, timeout=(15, 45), retries=1)
            html = r.text or ""
            base = str(getattr(r, "url", None) or page)
        except Exception as exc:
            log.info("live page fail %s: %s", page, exc)
            continue
        hrefs = re.findall(r'href=["\']([^"\']+)["\']', html, re.I)
        for h in hrefs:
            full = urljoin(base, html_lib.unescape(h))
            if ".pdf" not in full.lower() and "download.php" not in full.lower():
                continue
            if not _host_ok(full):
                continue
            host = (urlparse(full).hostname or "").lower()
            portal = f"live_{host}"
            if "cnlegis" in host:
                portal = "cnlegis.gov.mg_live"
            elif "ceni" in host:
                portal = "ceni-madagascar.mg_live"
            _add(
                items,
                seen,
                _ident_from_url(full),
                full,
                {"portal": portal, "title": _title_from_url(full)},
            )
        log.info("live %s catalog=%s", page[:70], len(items))
    log.info("live pages new=%s catalog=%s", len(items) - n0, len(items))


def discover_official_cdx(items, seen):
    if env_int("SKIP_CDX", 0):
        return
    prefixes = [
        ("www.assemblee-nationale.mg/wp-content/uploads/", "assemblee-nationale.mg_cdx"),
        ("assemblee-nationale.mg/wp-content/uploads/", "assemblee-nationale.mg_cdx"),
        ("www.hcc.gov.mg/wp-content/uploads/", "hcc.gov.mg_cdx"),
        ("hcc.gov.mg/wp-content/uploads/", "hcc.gov.mg_cdx"),
        ("www.primature.gov.mg/wp-content/uploads/", "primature.gov.mg_cdx"),
        ("primature.gov.mg/wp-content/uploads/", "primature.gov.mg_cdx"),
        ("mef.gov.mg/assets/file/", "mef.gov.mg_cdx"),
        ("www.mef.gov.mg/assets/file/", "mef.gov.mg_cdx"),
        ("www.ceni-madagascar.mg/wp-content/uploads/", "ceni-madagascar.mg_cdx"),
        ("ceni-madagascar.mg/wp-content/uploads/", "ceni-madagascar.mg_cdx"),
        ("www.tresorpublic.mg/", "tresorpublic.mg_cdx"),
        ("tresorpublic.mg/", "tresorpublic.mg_cdx"),
        ("www.presidence.gov.mg/wp-content/uploads/", "presidence.gov.mg_cdx"),
        ("presidence.gov.mg/wp-content/uploads/", "presidence.gov.mg_cdx"),
    ]
    limit = env_int("CDX_LIMIT", 400)
    n0 = len(items)
    digests = set()
    for prefix, portal in prefixes:
        hits = _cdx_with_retry(prefix, limit=limit)
        log.info("cdx %s hits=%s", prefix, len(hits))
        for h in hits:
            orig = (h.get("original") or "").strip()
            if not orig:
                continue
            if ".pdf" not in orig.lower() and "download.php" not in orig.lower():
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
            if "mef.gov.mg" in (urlparse(orig).hostname or "").lower():
                if not re.search(r"(?i)(loi|d[eé]cret|constit|code|ordonnance)", name):
                    if not re.search(r"(?i)\b(lfi?[-_]?\d{4}|loi[-_ ]?de[-_ ]?finances)\b", name):
                        continue
                    if re.search(r"(?i)(guide|calendrier|manuel|newsletter)", name):
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
    log.info("other cdx new=%s catalog=%s", len(items) - n0, len(items))


def discover():
    items, seen = [], set()
    discover_cnlegis_cdx(items, seen)
    discover_cnlegis_loi_live(items, seen)
    discover_tresor(items, seen)
    discover_an_textes(items, seen)
    discover_live_pages(items, seen)
    discover_official_cdx(items, seen)

    def rank(it):
        ident, url, meta = it
        portal = meta.get("portal") or ""
        path = unquote(urlparse(url).path).lower()
        title = (meta.get("title") or "").lower()
        score = 0
        if "constitut" in path or "constitut" in title:
            score -= 50_000
        elif "cnlegis.gov.mg_loi_live" in portal:
            score -= 48_000
        elif "cnlegis.gov.mg_loi" in portal or (
            "cnlegis" in portal and path.split("/")[-1].startswith("l")
        ):
            score -= 45_000
        elif "tresorpublic.mg_lois" in portal:
            score -= 42_000
        elif "cnlegis.gov.mg_ordo" in portal:
            score -= 40_000
        elif "assemblee-nationale" in portal and ("loi" in path or _is_an_numbered_loi(url)):
            score -= 38_000
        elif "organique" in title or "organique" in path or "ceni" in portal:
            score -= 35_000
        elif "cnlegis.gov.mg_decret" in portal or "tresorpublic.mg_decrets" in portal:
            score -= 28_000
        elif "hcc.gov.mg" in portal:
            score -= 30_000
        elif "primature" in portal and re.search(r"(?i)d[eé]cret|decret|loi", path + title):
            score -= 25_000
        elif "cnlegis" in portal:
            score -= 22_000
        elif "assemblee-nationale.mg_textes" in portal:
            score -= 18_000
        elif "primature" in portal:
            score -= 15_000
        elif "mef.gov.mg" in portal:
            score -= 8_000
        elif "live_" in portal:
            score -= 20_000
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
    if _is_an_numbered_loi(url) or _is_constitution(url, title) or _is_cnlegis_act(url):
        return bool(
            TEXT_KEEP_RE.search(text[:12000])
            or TEXT_KEEP_RE.search(text)
            or KEEP_RE.search(unquote(url))
        )
    return bool(TEXT_KEEP_RE.search(text[:6000]) or KEEP_RE.search(unquote(url) + " " + (title or "")))


def _date_from(ident: str, title: str, text: str) -> str | None:
    m = re.search(r"(?:^|-)([LDAO])(20\d{2}|19\d{2})", ident, re.I)
    if m:
        return f"{m.group(2)}-01-01"
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
        allow_ocr = env_int("OCR_ALL", 0) == 1 or (
            _is_constitution(url, title) and env_int("OCR_CONST", 1) == 1
        )

        got = fetch_mg(url, wayback_ts=wayback_ts, allow_ocr=allow_ocr)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(
                CC,
                {"identifier": ident, "source_url": url, "reason": got.get("error"), "portal": portal},
            )
            time.sleep(0.35)
            continue
        if not text_ok(text, url, title):
            fail += 1
            log_failure(
                CC,
                {
                    "identifier": ident,
                    "source_url": url,
                    "reason": "filter_no_loi_ordo_decret_const",
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
            collector="collect_mg.py",
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
        source=(
            "cnlegis.gov.mg (DIRCNLEGIS/SGG) / tresorpublic.mg / assemblee-nationale.mg / "
            "primature.gov.mg / hcc.gov.mg / mef.gov.mg / ceni-madagascar.mg"
        ),
        source_urls=[
            f"{CNLEGIS}/",
            f"{CNLEGIS}/uploads/",
            f"{APP_PRIMATURE}/gouvernement/decrets",
            f"{TRESOR}/?page_id=214&content=temp&type=loi",
            f"{AN}/",
            f"{AN}/textes/",
            f"{HCC}/",
            f"{PRIMATURE}/",
            f"{MEF}/",
            f"{CENI}/",
        ],
        license_text=LICENSE,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage=(
            "catalog-backed incomplete; cnlegis.gov.mg/uploads JO texts (L/D/O/A) via CDX+live; "
            "tresorpublic.mg lois/décrets live; assemblee-nationale.mg lois+Constitution CDX/Wayback "
            "+ live textes (official AN R2 CDN); primature/HCC/MEF/CENI. Live JO thin elsewhere."
        ),
        notes=(
            f"Official Madagascar acts only. portals={portals} methods={methods}. "
            "Not AfricanLII / Droit-Afrique. No WAF bypass. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s portals=%s methods=%s", ok, skip, fail, portals, methods)


if __name__ == "__main__":
    main()
