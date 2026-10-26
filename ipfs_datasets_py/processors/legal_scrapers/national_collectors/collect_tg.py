#!/usr/bin/env python3
"""Togo (tg): official law / JO PDFs from jo.gouv.tg + related *.gouv.tg hosts.

Official only:
  - https://jo.gouv.tg/  (Journal Officiel — /sites/default/files/JO/*.pdf live)
  - https://www.jo.gouv.tg/ (same files)
  - https://finances.gouv.tg/ (lois de finances when PDF)
  - https://justice.gouv.tg/ (textes / décrets / codes when PDF)
  - https://sgg.gouv.tg/ / primature.gouv.tg / www.gouv.tg (when reachable)
  - Assemblée nationale (assemblee-nationale.tg) via CDX only — live Cloudflare-gated (no WAF bypass)
  - Wayback/CDX of the same official *.gouv.tg / *.gov.tg URLs

Filter: JO fascicules kept; other hosts require loi/ordonnance/décret/constitution/code.
Skip PDFs >12MB. Not AfricanLII / Droit-Afrique. No WAF bypass. Not legal advice.
NOTE: country code tg = Togo (not Tajikistan / tj).
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
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit, quote, parse_qs

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

CC, COUNTRY, LANG = "tg", "Togo", "fr"
SOURCE_TYPE = "jo_togo_official"
LICENSE = (
    "République Togolaise — Journal Officiel (jo.gouv.tg) / Ministère des Finances "
    "(finances.gouv.tg) / Ministère de la Justice (justice.gouv.tg) / SGG / Primature / "
    "Assemblée nationale. Authentic Journal Officiel / official text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://jo.gouv.tg/; Togo=tg not Tajikistan)"
ART = re.compile(r"(?im)^\s*((?:Article|Art\.?)\s+\d+[a-zA-Zº°]?)\b")
log = logging.getLogger("tg")

JO = "https://jo.gouv.tg"
FINANCES = "https://finances.gouv.tg"
JUSTICE = "https://justice.gouv.tg"
MAX_PDF_BYTES = 8 * 1024 * 1024

ALLOWED = (
    "jo.gouv.tg",
    "finances.gouv.tg",
    "justice.gouv.tg",
    "sgg.gouv.tg",
    "primature.gouv.tg",
    "presidence.gouv.tg",
    "gouv.tg",
    "gov.tg",
    "assemblee-nationale.tg",
    "assembleenationale.tg",
    "courconstitutionnelle.tg",
    "cour-constitutionnelle.tg",
)

KEEP_RE = re.compile(
    r"(loi|ordonnance|ordonn|d[eé]cret|decret|arr[eê]t[eé]|arrete|constitution|code|"
    r"journal.?officiel|\bjos?\b|\bjo\b|organique|r[eè]glement|charte|statut|"
    r"/sites/default/files/jo/|/files/jo/|/publications/jos?_)",
    re.I,
)
DROP_RE = re.compile(
    r"(africanlii|togolii|droit-afrique|gazettes\.africa|law\.africa|"
    r"discours|allocution|communique|photo|banner|logo|cv[-_]|"
    r"biographie|rapport[-_ ]annuel|presentation|organigramme|"
    r"newsletter|recrutement|facebook|twitter|linkedin|"
    r"groupe-amitie|liste-alpha|suppleants|charpente/deputes|"
    r"concours|assurance/|carteprofessionnelle|ami-proalab|proalab|fournisseurs-guinee|fournisseurs-senegal)",
    re.I,
)
TEXT_KEEP_RE = re.compile(
    r"\b(loi|ordonnance|d[eé]cret|decret|constitution|journal\s+officiel|"
    r"code|r[eé]publique\s+togolaise|assembl[eé]e\s+nationale|"
    r"pr[eé]sident\s+de\s+la\s+r[eé]publique|promulgue|partie\s+officielle)\b",
    re.I,
)

SEED_PDFS = [
    # Constitution 2024 (JO spécial)
    "https://jo.gouv.tg/sites/default/files/JO/JOS_06_05_2024%20-%2069%20E%20ANNEE%20N%C2%B042%20BIS%20.pdf",
    "https://jo.gouv.tg/sites/default/files/JO/JOS_25_01_2024-69E%20ANNEE%20N%C2%B08%20BIS.pdf",
    "https://jo.gouv.tg/sites/default/files/JO/JOS_24_12_2024%20-%2069%20E%20ANNEE%20N%C2%B0129%20BIS.pdf",
    "https://jo.gouv.tg/sites/default/files/JO/JO_04_02_2026%2071E%20ANNEE%20N%C2%B0%208%20BIS_.pdf",
]

LISTING_SPECS = [
    # (url_template with {page}, max_pages, priority) — page 0 = no query
    ("https://jo.gouv.tg/lois", 12, 12),
    ("https://jo.gouv.tg/Lois", 4, 12),
    ("https://jo.gouv.tg/derniers_journaux_officiels", 6, 8),
    ("https://jo.gouv.tg/derniers_textes_publies", 8, 10),
    ("https://www.jo.gouv.tg/lois", 4, 14),
    ("https://www.jo.gouv.tg/derniers_journaux_officiels", 3, 9),
    ("https://jo.gouv.tg/", 1, 15),
    ("https://www.jo.gouv.tg/", 1, 15),
    ("https://finances.gouv.tg/", 1, 40),
    ("https://justice.gouv.tg/", 1, 45),
]


def _host_ok(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    if any(x in host for x in ("africanlii", "togolii", "droit-afrique", "gazettes.africa", "law.africa")):
        return False
    return any(host == s or host.endswith("." + s) for s in ALLOWED)


def _norm_url(url: str) -> str:
    url = html_lib.unescape((url or "").split("#")[0].strip())
    if not url:
        return ""
    url = url.replace(":80/", "/").replace(":80?", "?")
    if url.startswith("http://"):
        url = "https://" + url[len("http://") :]
    # Prefer bare jo.gouv.tg over www for same path
    try:
        p = urlsplit(url)
        host = (p.hostname or "").lower()
        if host == "www.jo.gouv.tg":
            host = "jo.gouv.tg"
        parts = []
        for seg in p.path.split("/"):
            if not seg:
                parts.append(seg)
                continue
            parts.append(seg if "%" in seg else quote(seg, safe="._-()[]',"))
        url = urlunsplit((p.scheme or "https", host, "/".join(parts), "", ""))
    except Exception:
        url = url.replace(" ", "%20")
    return url


def _ident_from_url(url: str) -> str:
    path = unquote(urlsplit(url).path)
    name = Path(path).name or path
    stem = Path(name).stem
    if "/sites/default/files/jo/" in path.lower() or "/files/jo/" in path.lower():
        return "jo-" + re.sub(r"\W+", "", stem)[:48].lower()
    return re.sub(r"\W+", "-", stem).strip("-").lower()[:160] or re.sub(r"\W+", "-", url)[-80:]


def _is_jo(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    path = unquote(urlsplit(url).path).lower()
    return "jo.gouv.tg" in host and ("/sites/default/files/jo/" in path or path.endswith(".pdf") and "/jo/" in path)


def _keep(url: str) -> bool:
    if not _host_ok(url):
        return False
    if DROP_RE.search(url):
        return False
    if _is_jo(url):
        return url.lower().endswith(".pdf")
    blob = unquote(urlsplit(url).path) + " " + url
    if not url.lower().endswith(".pdf"):
        return False
    return bool(KEEP_RE.search(blob))


def ocr_pdf(raw: bytes) -> str:
    max_pages = env_int("MAX_OCR_PAGES", 12)
    dpi = env_int("OCR_DPI", 140)
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


def fetch_tg(url: str, wayback_ts: str | None = None) -> dict:
    got = fetch_official(url, ua=UA, verify=False, min_text=120, wayback=True, wayback_ts=wayback_ts)
    if got.get("status") == "success" and len(got.get("text") or "") >= 120:
        return got
    body = got.get("content") or b""
    if not (isinstance(body, bytes) and body[:4] == b"%PDF"):
        try:
            r = live_get(url, ua=UA, verify=False, timeout=(20, 90), retries=2)
            if getattr(r, "status_code", 0) == 200 and (r.content or b"")[:4] == b"%PDF":
                body = r.content
        except Exception as exc:
            got["error"] = (got.get("error") or "") + f";live_pdf:{exc}"
            return got
    if not (isinstance(body, bytes) and body[:4] == b"%PDF"):
        return got
    if len(body) > MAX_PDF_BYTES:
        got["error"] = f"pdf_too_large:{len(body)}"
        return got
    text = pdf_to_text(body)
    if len(text) >= 120:
        got.update(status="success", text=text, content=body, method=got.get("method") or "http_pdf")
        return got
    max_ocr_bytes = env_int("MAX_OCR_BYTES", 8 * 1024 * 1024)
    if len(body) > max_ocr_bytes:
        got["error"] = (got.get("error") or "") + f";skip_ocr_large:{len(body)}"
        return got
    log.info("OCR fra %s bytes=%s", _ident_from_url(url)[:40], len(body))
    ocr = ocr_pdf(body)
    if len(ocr) >= 120:
        got.update(status="success", text=ocr, content=body, method="ocr_fra")
        return got
    got["error"] = (got.get("error") or "") + ";ocr_short"
    return got


def _add(items, seen, ident, url, ts=None, priority=50, size_hint=None):
    url = _norm_url(url)
    if not url or not _keep(url):
        return
    key = url.lower().split("?")[0]
    # collapse www/bare jo duplicates already handled in _norm_url
    if key in seen:
        return
    if size_hint and size_hint > MAX_PDF_BYTES:
        return
    seen.add(key)
    ident = re.sub(r"\W+", "-", (ident or _ident_from_url(url)).strip("-")).lower()[:160]
    items.append((priority, ident, url, ts, size_hint))


def _extract_pdfs(html: str, base: str):
    out = []
    for href in re.findall(r'href=["\']([^"\']+)["\']', html or "", re.I):
        full = urljoin(base, href.replace("&amp;", "&"))
        if ".pdf" in full.lower():
            out.append(full.split("#")[0])
    for m in re.findall(r'(https?://[^\s"\'<>]+\.pdf)', html or "", re.I):
        out.append(m.split("#")[0])
    for m in re.findall(r'/sites/default/files/[^\s"\'<>]+\.pdf', html or "", re.I):
        out.append(urljoin(base, m))
    return out


def discover():
    items = []
    seen = set()

    for seed in SEED_PDFS:
        _add(items, seen, _ident_from_url(seed), seed, ts=None, priority=5)

    for base, max_pages, pri in LISTING_SPECS:
        for page in range(0, max_pages):
            if page == 0:
                url = base
            else:
                sep = "&" if "?" in base else "?"
                url = f"{base}{sep}page={page}"
            try:
                r = live_get(url, ua=UA, verify=False, timeout=(15, 45), retries=2)
                if getattr(r, "status_code", 0) != 200:
                    if page == 0:
                        log.info("listing miss %s %s", url, getattr(r, "status_code", None))
                    break
                html = r.text or ""
                pdfs = _extract_pdfs(html, url)
                n = 0
                for pdf in pdfs:
                    p = pri
                    low = unquote(pdf).lower()
                    if "constitut" in low or "2024-005" in low or "06_05_2024" in low:
                        p = 5
                    elif re.search(r"/jos?[_\-]", low) or "/files/jo/" in low:
                        p = min(p, 12)
                    _add(items, seen, _ident_from_url(pdf), pdf, ts=None, priority=p)
                    n += 1
                log.info("listing %s page=%s pdfs=%s", base.split("/")[-1] or "home", page, n)
                if n == 0 and page > 0:
                    break
            except Exception as exc:
                log.info("listing %s %s", url, exc)
                break

    # Follow a few recent JO node pages for attached PDFs
    try:
        r = live_get(f"{JO}/", ua=UA, verify=False, timeout=(12, 40), retries=1)
        nodes = sorted(set(re.findall(r'href=["\']/node/(\d+)["\']', r.text or "")))[:18]
        for nid in nodes:
            nurl = f"{JO}/node/{nid}"
            try:
                nr = live_get(nurl, ua=UA, verify=False, timeout=(12, 35), retries=1)
                if getattr(nr, "status_code", 0) != 200:
                    continue
                for pdf in _extract_pdfs(nr.text or "", nurl):
                    _add(items, seen, _ident_from_url(pdf), pdf, ts=None, priority=16)
            except Exception as exc:
                log.info("node %s %s", nid, exc)
    except Exception as exc:
        log.info("home nodes %s", exc)

    cdx_prefixes = (
        "jo.gouv.tg/sites/default/files/JO/",
        "www.jo.gouv.tg/sites/default/files/JO/",
        "jo.gouv.tg/sites/default/files/",
        "finances.gouv.tg/wp-content/uploads/",
        "www.finances.gouv.tg/wp-content/uploads/",
        "justice.gouv.tg/sites/default/files/",
        "www.justice.gouv.tg/sites/default/files/",
        "sgg.gouv.tg/",
        "primature.gouv.tg/",
        "assemblee-nationale.tg/",
        "www.assemblee-nationale.tg/",
    )
    for prefix in cdx_prefixes:
        try:
            hits = cdx_urls(
                prefix,
                limit=env_int("CDX_LIMIT", 220),
                match_type="prefix",
                extra_filters=["statuscode:200", "mimetype:application/pdf"],
            ) or []
        except Exception as exc:
            log.info("cdx %s %s", prefix, exc)
            hits = []
        for h in hits:
            orig = h.get("original") or ""
            ts = (h.get("timestamp") or "")[:14] or None
            try:
                length = int(h.get("length") or 0)
            except Exception:
                length = 0
            if length and length > MAX_PDF_BYTES:
                continue
            if not _keep(orig):
                continue
            pri = 28
            if _is_jo(orig):
                pri = 18
            if re.search(r"(?i)constitut", orig):
                pri = 8
            if re.search(r"(?i)(loi|code|ordonnance)", unquote(orig)):
                pri = min(pri, 20)
            _add(items, seen, _ident_from_url(orig), orig, ts=ts, priority=pri, size_hint=length or None)

    items.sort(key=lambda x: (x[0], x[1]))
    out = [(ident, url, ts, size) for _, ident, url, ts, size in items]
    log.info("catalog %s", len(out))
    return out


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 80)
    max_seconds = env_int("MAX_SECONDS", 2400)
    t_start = time.time()
    done = existing_ids(CC)
    already = len(done)
    target_total = env_int("TARGET_TOTAL", 0)
    ok = skip = fail = 0
    for ident, url, ts, size_hint in discover():
        if max_new and ok >= max_new:
            break
        if target_total and (already + ok) >= target_total:
            break
        if time.time() - t_start > max_seconds:
            break
        if size_hint and size_hint > MAX_PDF_BYTES:
            skip += 1
            continue
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        got = fetch_tg(url, wayback_ts=ts)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error"), "wayback_ts": ts})
            continue
        if len(text) > 2_500_000:
            log.info("skip huge text chars=%s %s", len(text), ident[:50])
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "text_too_large", "chars": len(text)})
            continue
        if not TEXT_KEEP_RE.search(text[:5000]) and not _is_jo(url):
            if not re.search(r"(?i)(loi|ordonnance|decret|constitut|code)", ident):
                fail += 1
                log_failure(CC, {"identifier": ident, "source_url": url, "reason": "text_not_legal"})
                continue
        title = None
        for line in text.splitlines():
            if len(line.strip()) > 18:
                title = line.strip()[:240]
                break
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title or ident, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_tg.py",
            article_re=ART,
            extra_meta={"fetch_method": got.get("method"), "wayback_ts": ts, "size_hint": size_hint},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s ts=%s", ident[:60], got.get("method"), len(text), ts)
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY,
        source="Togo Journal Officiel (jo.gouv.tg) / finances.gouv.tg / justice.gouv.tg",
        source_urls=[
            "https://jo.gouv.tg/",
            "https://jo.gouv.tg/lois",
            "https://jo.gouv.tg/derniers_journaux_officiels",
            "https://finances.gouv.tg/",
            "https://justice.gouv.tg/",
        ],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (jo.gouv.tg JO fascicules live + CDX; finances/justice lean; AN CDX only)",
        notes="Official *.gouv.tg / JO PDFs only. OCR fra for scans. Not AfricanLII. No WAF bypass. Not legal advice. tg=Togo.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s total_instruments=%s", ok, skip, fail, len(done))


if __name__ == "__main__":
    main()
