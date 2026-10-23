#!/usr/bin/env python3
"""Burkina Faso (bf): official JO + laws from JOBF / AN / Justice / Primature / Gouvernement.

Official only:
  - https://jobf.gov.bf/  (Journal Officiel — live API frontoffice + /storage PDFs)
  - https://www.assembleenationale.bf/loip (adopted laws storage/Loi)
  - https://www.justice.gov.bf/files/.../Textes juridiques (CDX/Wayback; live empty)
  - https://primature.gov.bf/ (CDX Downloads/Codes + fileadmin)
  - https://gouvernement.gov.bf/download/ (lois/décrets)
  - https://www.legiburkina.bf/Documents/ (historical official codes via CDX; live DNS-dead)
  - https://legiburkina.gov.bf/ (SGG-CM SPA — API not used; no WAF bypass)

Filter: JO fascicules kept; other hosts require loi/ordonnance/décret/constitution/code.
Not AfricanLII / Droit-Afrique. No WAF bypass. Not legal advice.
"""
from __future__ import annotations

import html as html_lib
import json
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

CC, COUNTRY, LANG = "bf", "Burkina Faso", "fr"
SOURCE_TYPE = "jo_burkinafaso_jobf"
LICENSE = (
    "Journal Officiel du Burkina Faso (jobf.gov.bf / SGG-CM) / Assemblée nationale "
    "(assembleenationale.bf) / Ministère de la Justice (justice.gov.bf) / Primature / "
    "Gouvernement. Authentic Journal Officiel / official text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://jobf.gov.bf/)"
ART = re.compile(r"(?im)^\s*((?:Article|Art\.?)\s+\d+[a-zA-Zº°]?)\b")
log = logging.getLogger("bf")

JOBF = "https://jobf.gov.bf"
AN = "https://www.assembleenationale.bf"
JUSTICE = "https://www.justice.gov.bf"
PRIMATURE = "https://primature.gov.bf"
GOUV = "https://gouvernement.gov.bf"

ALLOWED_HOST_SUFFIXES = (
    "jobf.gov.bf",
    "assembleenationale.bf",
    "an.bf",
    "justice.gov.bf",
    "primature.gov.bf",
    "gouvernement.gov.bf",
    "legiburkina.bf",
    "legiburkina.gov.bf",
    "sggcm.gov.bf",
    "sig.gov.bf",
    "finances.gov.bf",
    "conseil-constitutionnel.gov.bf",
    "service-public.gov.bf",
    "servicepublic.gov.bf",
    "gov.bf",
)

KEEP_RE = re.compile(
    r"(loi|ordonnance|ordonn|d[eé]cret|decret|constitution|code|"
    r"journal.?officiel|\bjo\b|texte.?juridique|organique|newspaper)",
    re.I,
)
DROP_RE = re.compile(
    r"(discours|allocution|communique|photo|banner|logo|cv[-_]|"
    r"biographie|rapport[-_ ]|presentation|organigramme|ouverture_session|"
    r"forum_femme|libelexpomotif|libelcranal|libelrapport|libelpv|"
    r"expose.?des.?motifs|compte.?rendu|"
    r"decision_\d+|avis_\d+|election_2012|thme_du_casem|casem_2014)",
    re.I,
)
TEXT_KEEP_RE = re.compile(
    r"\b(loi|ordonnance|d[eé]cret|decret|constitution|journal\s+officiel|"
    r"code|bulletin des lois|r[eé]publique du burkina|burkina\s+faso|"
    r"partie\s+officielle|pr[eé]sidence\s+du\s+faso)\b",
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
        q = parse_qs(p.query, keep_blank_values=False)
        if "wpdmdl" in q or "/download/" in p.path:
            keep = {}
            if "wpdmdl" in q:
                keep["wpdmdl"] = q["wpdmdl"][0]
            query = "&".join(f"{k}={quote(str(v), safe='')}" for k, v in keep.items())
        else:
            query = ""
        parts = []
        for seg in p.path.split("/"):
            if not seg:
                parts.append(seg)
                continue
            parts.append(seg if "%" in seg else quote(seg, safe="._-()[]',"))
        url = urlunsplit((p.scheme or "https", p.netloc, "/".join(parts), query, ""))
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
    if "/storage/Loi/" in url or "/storage/loi/" in url:
        return "an-loi-" + re.sub(r"\W+", "", stem)[:40].lower()
    if "jobf.gov.bf" in (urlparse(url).hostname or "").lower() and "/storage/newspapers/" in url:
        return "jo-" + re.sub(r"\W+", "", stem)[:48].lower()
    return re.sub(r"\W+", "-", stem).strip("-").lower()[:160] or re.sub(r"\W+", "-", url)[-80:]


def _title_from_url(url: str) -> str:
    name = unquote(Path(urlparse(url).path).name)
    stem = Path(name).stem
    if "/download/" in url:
        slug = unquote(urlparse(url).path.rstrip("/").split("/")[-1])
        return slug.replace("-", " ").replace("_", " ")[:240]
    return stem.replace("_", " ").replace("-", " ")[:240] or stem


def _is_jo(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    path = unquote(urlparse(url).path).lower()
    return "jobf.gov.bf" in host and ("/storage/newspapers/" in path or "newspaper" in path)


def _is_an_loi_storage(url: str) -> bool:
    return "assembleenationale.bf" in (urlparse(url).hostname or "").lower() and "/storage/loi/" in url.lower()


def _is_justice_codes(url: str) -> bool:
    path = unquote(urlparse(url).path).lower()
    host = (urlparse(url).hostname or "").lower()
    return "justice.gov.bf" in host and "textes" in path and (
        "codes" in path or "lois" in path or "decret" in path or "ordonn" in path or "constit" in path
    )


def _keep_name(url: str, title: str | None = None) -> bool:
    if _is_jo(url) or _is_an_loi_storage(url):
        return True
    blob = unquote(urlparse(url).path) + " " + (title or "") + " " + url
    if DROP_RE.search(blob):
        return False
    if "gouvernement.gov.bf" in blob.lower() and "/download/" in blob.lower():
        return bool(KEEP_RE.search(blob))
    if ".pdf" not in url.lower() and "/download/" not in url.lower():
        return False
    return bool(KEEP_RE.search(blob))


def _add(items, seen, ident, url, meta=None):
    url = _norm_url(url)
    if not url or not _host_ok(url):
        return
    if ".pdf" not in url.lower() and "/download/" not in url.lower():
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


def _jobf_post(path: str, payload: dict | None = None, timeout: int = 90) -> dict:
    """POST JSON to jobf.gov.bf/api/... using live_get-compatible session via urllib."""
    import urllib.request
    import ssl

    url = JOBF + "/api/" + path.lstrip("/")
    body = json.dumps(payload or {}).encode("utf-8")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "User-Agent": UA,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        raw = resp.read()
    return json.loads(raw.decode("utf-8", "replace"))


def _jobf_resolve_pdf(uuid: str) -> tuple[str | None, dict]:
    """Resolve JO uuid → public storage PDF URL via newspapers/jo-file-url."""
    try:
        d = _jobf_post("newspapers/jo-file-url", {"joUuid": uuid}, timeout=45)
    except Exception as exc:
        return None, {"error": f"jo_file_url:{exc}"}
    if not d.get("success"):
        return None, {"error": f"jo_file_url_fail:{d.get('message')}"}
    path_jo = ((d.get("data") or {}).get("pathJo") or "").lstrip("/")
    if not path_jo or not path_jo.lower().endswith(".pdf"):
        return None, {"error": "jo_file_url_no_path"}
    return f"{JOBF}/storage/{path_jo}", d.get("data") or {}


def fetch_jobf_pdf(url: str, *, allow_ocr: bool = False) -> dict:
    """Download JOBF storage PDF (live)."""
    try:
        r = live_get(url, ua=UA, verify=False, timeout=(20, 120), retries=2)
        body = r.content or b""
    except Exception as exc:
        return {"status": "error", "error": f"jobf_dl:{exc}", "text": "", "content": b""}
    if not (isinstance(body, bytes) and body[:4] == b"%PDF"):
        return {"status": "error", "error": "jobf_not_pdf", "text": "", "content": body}
    if len(body) > MAX_PDF_BYTES:
        return {"status": "error", "error": f"too_large:{len(body)}", "text": "", "content": b""}
    text = pdf_to_text(body)
    if len(re.sub(r"[\x0c\s]+", "", text or "")) >= 100:
        return {"status": "success", "text": text, "content": body, "method": "jobf_storage_pdf"}
    if not allow_ocr:
        return {
            "status": "error",
            "error": "jobf_scan_no_ocr",
            "text": text or "",
            "content": body,
            "method": "jobf_storage_pdf_empty",
        }
    max_ocr_bytes = env_int("MAX_OCR_BYTES", 8 * 1024 * 1024)
    if len(body) > max_ocr_bytes:
        return {"status": "error", "error": f"ocr_skip_too_large:{len(body)}", "text": "", "content": body}
    log.info("OCR fra JOBF %s bytes=%s", url.split("/")[-1][:50], len(body))
    ocr = ocr_pdf(body)
    if len(ocr) >= 100:
        return {"status": "success", "text": ocr, "content": body, "method": "jobf_storage_pdf_ocr_fra"}
    return {"status": "error", "error": "ocr_short", "text": ocr or "", "content": body}


def fetch_bf(url: str, *, wayback_ts: str | None = None, allow_ocr: bool = True) -> dict:
    if _is_jo(url) or (urlparse(url).hostname or "").lower().endswith("jobf.gov.bf"):
        return fetch_jobf_pdf(url, allow_ocr=allow_ocr)

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
    max_ocr_bytes = env_int("MAX_OCR_BYTES", 12 * 1024 * 1024)
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


def discover_jobf(items, seen):
    """Live JOBF JO catalog — defer pathJo resolve to fetch (survives mid-probe kills)."""
    if env_int("SKIP_JOBF", 0):
        log.info("SKIP_JOBF=1")
        return
    max_pages = env_int("JOBF_MAX_PAGES", 12)  # 10/page → ~120 UUIDs fast
    n0 = len(items)
    catalog_rows = []
    for page in range(1, max_pages + 1):
        try:
            d = _jobf_post(f"frontoffice/newspapers/page/{page}", {}, timeout=60)
        except Exception as exc:
            log.info("jobf page %s fail: %s", page, exc)
            break
        data = d.get("data")
        rows = []
        if isinstance(data, dict):
            rows = data.get("data") or []
            last = int(data.get("last_page") or 0)
            log.info(
                "jobf page=%s n=%s total=%s last=%s",
                page, len(rows), data.get("total"), last,
            )
            if page >= last > 0:
                catalog_rows.extend(rows)
                break
        elif isinstance(data, list):
            rows = data
            log.info("jobf page=%s list n=%s", page, len(rows))
        else:
            log.info("jobf page=%s unexpected", page)
            break
        if not rows:
            break
        catalog_rows.extend(rows)
        time.sleep(0.15)

    catalog_rows.sort(key=lambda r: r.get("date_pub") or "", reverse=True)
    added = 0
    for row in catalog_rows:
        uuid = (row.get("uuid") or "").strip()
        if not uuid:
            continue
        numero = str(row.get("numero") or "").strip()
        typ = (row.get("type") or "ordinaire").strip()
        date_pub = (row.get("date_pub") or "")[:10]
        year = date_pub[:4] if date_pub else "xxxx"
        ident = re.sub(r"\W+", "-", f"jo-{year}-n{numero}-{typ}").strip("-").lower()[:160]
        # Placeholder URL — real storage path resolved at fetch via jo_uuid
        placeholder = f"{JOBF}/api/jo/{uuid}.pdf"
        title = f"Journal Officiel du Burkina Faso — n° {numero} ({typ}) {date_pub}".strip()
        if placeholder in seen:
            continue
        # Bypass _add .pdf host check carefully — use synthetic jobf URL
        seen.add(placeholder)
        items.append(
            (
                ident,
                placeholder,
                {
                    "portal": "jobf.gov.bf_jo",
                    "title": title,
                    "jo_uuid": uuid,
                    "jo_numero": numero,
                    "jo_type": typ,
                    "date_pub": date_pub,
                    "cdx_length": int(row.get("taille_jo") or 0) or None,
                },
            )
        )
        added += 1
    log.info("jobf new=%s catalog=%s rows=%s", added, len(items), len(catalog_rows))


def discover_justice_cdx(items, seen):
    if env_int("SKIP_CDX", 0):
        return
    limit = env_int("CDX_JUSTICE_LIMIT", 120)
    n0 = len(items)
    digests = set()
    for prefix in (
        "justice.gov.bf/files/Documents",
        "www.justice.gov.bf/files/Documents",
        "justice.gov.bf/files/",
        "www.justice.gov.bf/files/",
    ):
        hits = _cdx_with_retry(prefix, limit=limit)
        log.info("cdx justice %s hits=%s", prefix, len(hits))
        for h in hits:
            orig = (h.get("original") or "").strip()
            if not orig or ".pdf" not in orig.lower():
                continue
            path = unquote(urlparse(orig).path).lower()
            if "textes" not in path and "codes" not in path and "constit" not in path:
                if "loi" not in path and "decret" not in path and "ordonn" not in path:
                    continue
            name = unquote(Path(urlparse(orig).path).name)
            if DROP_RE.search(name):
                continue
            dig = h.get("digest") or _norm_url(orig)
            if dig in digests:
                continue
            digests.add(dig)
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
                    "portal": "justice.gov.bf_cdx",
                    "title": _title_from_url(orig),
                    "wayback_ts": h.get("timestamp"),
                    "cdx_length": length,
                },
            )
    log.info("justice cdx new=%s catalog=%s", len(items) - n0, len(items))


def discover_legiburkina_cdx(items, seen):
    """Historical official codes on legiburkina.bf (DNS-dead; CDX/Wayback only)."""
    if env_int("SKIP_CDX", 0) or env_int("SKIP_LEGIBURKINA", 0):
        return
    limit = env_int("CDX_LEGI_LIMIT", 80)
    n0 = len(items)
    digests = set()
    for prefix in (
        "legiburkina.bf/Documents/",
        "www.legiburkina.bf/Documents/",
        "legiburkina.bf/documents/",
        "www.legiburkina.bf/documents/",
    ):
        hits = _cdx_with_retry(prefix, limit=limit)
        log.info("cdx legi %s hits=%s", prefix, len(hits))
        for h in hits:
            orig = (h.get("original") or "").strip()
            if not orig or ".pdf" not in orig.lower():
                continue
            name = unquote(Path(urlparse(orig).path).name)
            if not KEEP_RE.search(name):
                continue
            if DROP_RE.search(name):
                continue
            dig = h.get("digest") or _norm_url(orig)
            if dig in digests:
                continue
            digests.add(dig)
            _add(
                items,
                seen,
                _ident_from_url(orig),
                orig,
                {
                    "portal": "legiburkina.bf_cdx",
                    "title": _title_from_url(orig),
                    "wayback_ts": h.get("timestamp"),
                },
            )
    log.info("legi cdx new=%s catalog=%s", len(items) - n0, len(items))


def discover_an_cdx(items, seen):
    if env_int("SKIP_CDX", 0):
        return
    limit = env_int("CDX_AN_LIMIT", 200)
    n0 = len(items)
    digests = set()
    for prefix in (
        "assembleenationale.bf/IMG/pdf/loi_",
        "www.assembleenationale.bf/IMG/pdf/loi_",
        "assembleenationale.bf/IMG/pdf/constitution",
        "www.assembleenationale.bf/IMG/pdf/constitution",
        "assembleenationale.bf/IMG/pdf/code_",
        "www.assembleenationale.bf/IMG/pdf/code_",
        "assembleenationale.bf/IMG/pdf/ordonnance",
        "www.assembleenationale.bf/IMG/pdf/ordonnance",
    ):
        hits = _cdx_with_retry(prefix, limit=limit)
        log.info("cdx AN %s hits=%s", prefix, len(hits))
        for h in hits:
            orig = (h.get("original") or "").strip()
            if not orig or ".pdf" not in orig.lower():
                continue
            name = unquote(Path(urlparse(orig).path).name)
            if DROP_RE.search(name):
                continue
            dig = h.get("digest") or _norm_url(orig)
            if dig in digests:
                continue
            digests.add(dig)
            _add(
                items,
                seen,
                _ident_from_url(orig),
                orig,
                {
                    "portal": "assembleenationale.bf_cdx",
                    "title": _title_from_url(orig),
                    "wayback_ts": h.get("timestamp"),
                },
            )
    log.info("AN cdx new=%s catalog=%s", len(items) - n0, len(items))


def discover_an_loip(items, seen):
    """Live AN loip listing → detail pages → storage/Loi PDFs."""
    if env_int("SKIP_AN_LOIP", 0):
        return
    n0 = len(items)
    ids = []
    id_seen = set()
    max_list = env_int("AN_LOIP_LIST_PAGES", 15)
    for page in range(1, max_list + 1):
        url = f"{AN}/loip" if page == 1 else f"{AN}/loip?page={page}"
        try:
            r = live_get(url, ua=UA, verify=False, timeout=(15, 45), retries=2)
            body = r.text or ""
        except Exception as exc:
            log.info("loip list fail page=%s: %s", page, exc)
            break
        found = 0
        for href in re.findall(r'href=["\']([^"\']*loip/[^"\']+)["\']', body, re.I):
            full = urljoin(url, href.split("#")[0])
            m = re.search(r"/loip/(\d+)", full)
            if not m:
                continue
            lid = m.group(1)
            if lid in id_seen:
                continue
            id_seen.add(lid)
            ids.append(lid)
            found += 1
        log.info("loip list page=%s ids=%s new=%s", page, found, found)
        if found == 0:
            break
        time.sleep(0.3)

    cap = env_int("AN_LOIP_DETAIL_CAP", 80)
    log.info("loip detail crawl start n=%s (of %s ids)", min(cap, len(ids)), len(ids))
    for i, lid in enumerate(ids[:cap], 1):
        page_url = f"{AN}/loip/{lid}"
        try:
            r = live_get(page_url, ua=UA, verify=False, timeout=(12, 40), retries=1)
            body = r.text or ""
        except Exception as exc:
            log.info("loip detail fail %s: %s", lid, exc)
            continue
        title_m = re.search(r"<title[^>]*>(.*?)</title>", body, re.I | re.S)
        page_title = (title_m.group(1).strip().split("|")[0].strip() if title_m else "")[:240]
        h1 = re.search(r"<h1[^>]*>\s*([^<]{8,240})", body, re.I)
        if h1:
            page_title = h1.group(1).strip()[:240] or page_title
        for href in re.findall(r'href=["\']([^"\']+/storage/Loi/[^"\']+\.pdf)["\']', body, re.I):
            pdf = urljoin(page_url, href.split("#")[0])
            _add(
                items,
                seen,
                f"an-loip-{lid}",
                pdf,
                {
                    "portal": "assembleenationale.bf_loip",
                    "title": page_title or _title_from_url(pdf),
                    "page_url": page_url,
                    "loip_id": lid,
                },
            )
        if i % 10 == 0:
            log.info("loip detail progress %s/%s catalog=%s", i, min(cap, len(ids)), len(items))
        time.sleep(0.35)
    log.info("loip new=%s catalog=%s", len(items) - n0, len(items))


def discover_primature_cdx(items, seen):
    if env_int("SKIP_CDX", 0):
        return
    limit = env_int("CDX_PRIMATURE_LIMIT", 80)
    n0 = len(items)
    for prefix in (
        "primature.gov.bf/Downloads/",
        "www.primature.gov.bf/Downloads/",
        "primature.gov.bf/fileadmin/",
        "www.primature.gov.bf/fileadmin/",
    ):
        hits = _cdx_with_retry(prefix, limit=limit)
        log.info("cdx primature %s hits=%s", prefix, len(hits))
        for h in hits:
            orig = (h.get("original") or "").strip()
            if not orig or ".pdf" not in orig.lower():
                continue
            name = unquote(Path(urlparse(orig).path).name)
            if DROP_RE.search(name):
                continue
            if not KEEP_RE.search(name) and "Codes/" not in orig and "Codes%2F" not in orig:
                continue
            _add(
                items,
                seen,
                _ident_from_url(orig),
                orig,
                {
                    "portal": "primature.gov.bf_cdx",
                    "title": _title_from_url(orig),
                    "wayback_ts": h.get("timestamp"),
                },
            )
    log.info("primature cdx new=%s catalog=%s", len(items) - n0, len(items))


def discover_gouv_cdx(items, seen):
    if env_int("SKIP_CDX", 0):
        return
    limit = env_int("CDX_GOUV_LIMIT", 80)
    n0 = len(items)
    digests = set()
    for prefix in (
        "gouvernement.gov.bf/download/",
        "www.gouvernement.gov.bf/download/",
    ):
        hits = _cdx_with_retry(prefix, limit=limit)
        log.info("cdx gouv %s hits=%s", prefix, len(hits))
        for h in hits:
            orig = (h.get("original") or "").strip()
            if not orig:
                continue
            key = _norm_url(orig)
            if key in digests:
                continue
            digests.add(key)
            if not KEEP_RE.search(unquote(orig)):
                continue
            _add(
                items,
                seen,
                _ident_from_url(orig),
                orig,
                {
                    "portal": "gouvernement.gov.bf_download",
                    "title": _title_from_url(orig),
                    "wayback_ts": h.get("timestamp"),
                },
            )
    log.info("gouv cdx new=%s catalog=%s", len(items) - n0, len(items))


def discover():
    items, seen = [], set()
    # High-value small codes first via CDX, then live JOBF, then AN loip
    discover_justice_cdx(items, seen)
    discover_legiburkina_cdx(items, seen)
    discover_an_cdx(items, seen)
    discover_primature_cdx(items, seen)
    discover_gouv_cdx(items, seen)
    discover_jobf(items, seen)
    if env_int("AN_LOIP", 0) == 1:
        discover_an_loip(items, seen)
    else:
        log.info("AN_LOIP=0 — skip live loip detail crawl (enable AN_LOIP=1 to include)")

    def rank(it):
        ident, url, meta = it
        portal = meta.get("portal") or ""
        path = unquote(urlparse(url).path).lower()
        title = (meta.get("title") or "").lower()
        score = 0
        if "constitution" in path or "constitution" in title:
            score -= 5000
        elif "justice.gov.bf_cdx" in portal and ("codes" in path or "lois" in path):
            score -= 4500
        elif "legiburkina.bf_cdx" in portal:
            score -= 4200
        elif "jobf.gov.bf_jo" in portal:
            # prefer smaller / special issues slightly; still after codes
            length = meta.get("cdx_length") or 0
            date = meta.get("date_pub") or ""
            score -= 3500
            if length and length < 2_000_000:
                score -= 50
            if length and length > 8_000_000:
                score += 100
            # newer JO first among JO
            score -= int(date[:4] or 0) if date[:4].isdigit() else 0
        elif "assembleenationale.bf_loip" in portal:
            try:
                lid = int(meta.get("loip_id") or 0)
            except Exception:
                lid = 0
            score -= 3000 + min(lid, 500)
        elif "assembleenationale.bf_cdx" in portal:
            score -= 2000
        elif "gouvernement.gov.bf" in portal:
            score -= 1500
        elif "primature" in portal and "Codes" in url:
            score -= 1800
        elif "primature" in portal:
            score -= 800
        return (score, url)

    items.sort(key=rank)
    log.info("catalog total=%s", len(items))
    return items


def text_ok(text: str, url: str) -> bool:
    if not text or len(text) < 100:
        return False
    if _is_jo(url) or _is_an_loi_storage(url) or _is_justice_codes(url):
        return bool(TEXT_KEEP_RE.search(text[:12000]) or TEXT_KEEP_RE.search(text))
    return bool(TEXT_KEEP_RE.search(text[:6000]) or KEEP_RE.search(unquote(url)))


def _date_from(ident: str, title: str, text: str, meta: dict) -> str | None:
    if meta.get("date_pub") and re.match(r"\d{4}-\d{2}-\d{2}", meta["date_pub"]):
        return meta["date_pub"][:10]
    blob = f"{title} {ident} {(meta or {}).get('loi_num') or ''}"
    m = re.search(
        r"(?:du\s+)?(\d{1,2})\s+(janvier|f[eé]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|octobre|novembre|d[eé]cembre)\s+(20\d{2}|19\d{2})",
        blob,
        re.I,
    )
    months = {
        "janvier": 1, "fevrier": 2, "février": 2, "mars": 3, "avril": 4, "mai": 5,
        "juin": 6, "juillet": 7, "aout": 8, "août": 8, "septembre": 9,
        "octobre": 10, "novembre": 11, "decembre": 12, "décembre": 12,
    }
    if m:
        mon = months.get(m.group(2).lower())
        if mon:
            return f"{m.group(3)}-{mon:02d}-{int(m.group(1)):02d}"
    m2 = re.search(r"(20\d{2}|19\d{2})[-_/](\d{1,2})[-_/](\d{1,2})", blob)
    if m2:
        return f"{m2.group(1)}-{int(m2.group(2)):02d}-{int(m2.group(3)):02d}"
    m3 = re.search(r"\b(20\d{2}|19\d{2})\b", blob + " " + text[:400])
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
            ("jobf" in portal and env_int("OCR_JO", 0) == 1)
            or ("justice" in portal and env_int("OCR_JUSTICE", 1) == 1)
            or ("legi" in portal and env_int("OCR_LEGI", 1) == 1)
            or ("loip" in portal and env_int("OCR_AN", 0) == 1)
        )

        # Resolve JOBF placeholder → public /storage PDF
        if meta.get("jo_uuid") and "/api/jo/" in url:
            pdf_url, info = _jobf_resolve_pdf(meta["jo_uuid"])
            if not pdf_url:
                fail += 1
                log_failure(
                    CC,
                    {
                        "identifier": ident,
                        "source_url": url,
                        "reason": (info or {}).get("error") or "jo_resolve_fail",
                        "portal": portal,
                    },
                )
                time.sleep(0.25)
                continue
            url = pdf_url
            if info.get("pathJo"):
                meta["path_jo"] = info.get("pathJo")
            time.sleep(0.15)

        got = fetch_bf(url, wayback_ts=wayback_ts, allow_ocr=allow_ocr)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(
                CC,
                {"identifier": ident, "source_url": url, "reason": got.get("error"), "portal": portal},
            )
            time.sleep(0.3)
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

        if not title or title.startswith("Journal Officiel"):
            for ln in text.splitlines():
                s = ln.strip()
                if len(s) > 18 and re.search(
                    r"(?i)\b(journal\s+officiel|loi|constitution|ordonnance|d[eé]cret|code)\b",
                    s,
                ):
                    if not title.startswith("Journal Officiel") or "journal officiel" in s.lower():
                        if not title or len(s) > len(title):
                            title = s[:240]
                    break
            if not title:
                title = next(
                    (ln.strip()[:240] for ln in text.splitlines() if len(ln.strip()) > 18),
                    _title_from_url(url),
                )

        method = got.get("method") or ""
        if save_instrument(
            cc=CC,
            country=COUNTRY,
            language=LANG,
            ident=ident,
            title=title,
            text=text,
            source_url=meta.get("page_url") or url,
            source_type=SOURCE_TYPE,
            license_text=LICENSE,
            collector="collect_bf.py",
            date=_date_from(ident, title, text, meta),
            article_re=ART,
            extra_meta={
                "fetch_method": method,
                "portal": portal,
                "wayback_ts": wayback_ts,
                "jo_uuid": meta.get("jo_uuid"),
                "pdf_url": url,
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
        time.sleep(0.3)

    write_summary(
        CC,
        country=COUNTRY,
        source="JOBF Journal Officiel / Assemblée nationale / Justice / Primature / Gouvernement",
        source_urls=[
            "https://jobf.gov.bf/",
            "https://jobf.gov.bf/api/frontoffice/newspapers/page/1",
            "https://www.assembleenationale.bf/loip",
            "https://www.justice.gov.bf/",
            "https://primature.gov.bf/",
            "https://gouvernement.gov.bf/",
            "https://www.legiburkina.bf/Documents/",
        ],
        license_text=LICENSE,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage=(
            "catalog-backed incomplete; jobf.gov.bf JO live API (~894 issues) primary; "
            "justice.gov.bf Textes juridiques Codes et Lois via CDX/Wayback; "
            "assembleenationale.bf loip storage/Loi live; legiburkina.bf Documents CDX; "
            "primature/gouvernement supplements. JO scans may need OCR_JO=1."
        ),
        notes=(
            f"Official Burkina Faso acts only. portals={portals} methods={methods}. "
            "Not AfricanLII. No WAF bypass. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s portals=%s methods=%s", ok, skip, fail, portals, methods)


if __name__ == "__main__":
    main()
