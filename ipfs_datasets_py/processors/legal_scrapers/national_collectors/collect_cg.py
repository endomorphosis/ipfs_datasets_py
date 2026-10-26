#!/usr/bin/env python3
"""Republic of the Congo / Congo-Brazzaville (cg): official law / JO PDFs from *.cg / *.gouv.cg.

Official only (Brazzaville — NOT DRC / Congo-Kinshasa / cd):
  - https://sgg.cg/ (Secrétariat Général du Gouvernement)
  - https://www.primature.gouv.cg/ / primature.gouv.cg
  - https://presidence.cg/
  - https://assemblee-nationale.cg/
  - https://www.finances.gouv.cg/ / finances.gouv.cg
  - https://gouvernement.cg/
  - justice.gouv.cg / JO / SGG hosts when PDF (live or CDX)
  - Wayback/CDX of the same official *.cg / *.gouv.cg URLs

Filter: prefer loi/ordonnance/décret/constitution/code/JO; skip PDFs >12MB.
Not AfricanLII / Droit-Afrique. No WAF bypass. Not legal advice.
NOTE: country code cg = Congo-Brazzaville / République du Congo (not DRC cd, not CAR cf).
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
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit, quote

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

CC, COUNTRY, LANG = "cg", "Republic of the Congo", "fr"
SOURCE_TYPE = "jo_congo_brazzaville_official"
LICENSE = (
    "République du Congo / Congo-Brazzaville — SGG (sgg.cg) / Primature "
    "(primature.gouv.cg) / Présidence (presidence.cg) / Assemblée nationale "
    "(assemblee-nationale.cg) / Finances / Gouvernement / Justice / Journal Officiel "
    "(*.cg / *.gouv.cg). Authentic Journal Officiel / official text prevails. "
    "Not legal advice. Not DRC / Congo-Kinshasa (cd)."
)
UA = (
    "legal-corpora-collector/1.0 (research; source=https://sgg.cg/; "
    "Congo-Brazzaville=cg not DRC/cd)"
)
ART = re.compile(r"(?im)^\s*((?:Article|Art\.?)\s+\d+[a-zA-Zº°]?)\b")
log = logging.getLogger("cg")

MAX_PDF_BYTES = 12 * 1024 * 1024

ALLOWED = (
    "sgg.cg",
    "www.sgg.cg",
    "sgg.gouv.cg",
    "www.sgg.gouv.cg",
    "gouv.cg",
    "www.gouv.cg",
    "gov.cg",
    "www.gov.cg",
    "gouvernement.cg",
    "www.gouvernement.cg",
    "primature.gouv.cg",
    "www.primature.gouv.cg",
    "primature.cg",
    "presidence.cg",
    "www.presidence.cg",
    "presidence.gouv.cg",
    "www.presidence.gouv.cg",
    "assemblee-nationale.cg",
    "www.assemblee-nationale.cg",
    "assembleenationale.cg",
    "www.assembleenationale.cg",
    "an.cg",
    "an.gouv.cg",
    "finances.gouv.cg",
    "www.finances.gouv.cg",
    "economie.gouv.cg",
    "www.economie.gouv.cg",
    "justice.gouv.cg",
    "www.justice.gouv.cg",
    "justice.cg",
    "journalofficiel.gouv.cg",
    "www.journalofficiel.gouv.cg",
    "journalofficiel.cg",
    "www.journalofficiel.cg",
    "jo.gouv.cg",
    "www.jo.gouv.cg",
    "jo.cg",
)

KEEP_RE = re.compile(
    r"(loi|ordonnance|ordonn|d[eé]cret|decret|arr[eê]t[eé]|arrete|constitution|code|"
    r"journal.?officiel|\bjos?\b|\bjo\b|organique|r[eè]glement|charte|statut|"
    r"wp-content/uploads|/uploads/|/documents?/|/jo/|textes?|"
    r"brazzaville|r[eé]publique.?du.?congo)",
    re.I,
)
DROP_RE = re.compile(
    r"(africanlii|congoli|droit-afrique|gazettes\.africa|law\.africa|"
    r"discours|allocution|communique|photo|banner|logo|cv[-_]|"
    r"biographie|rapport[-_ ]annuel|presentation|organigramme|"
    r"newsletter|recrutement|facebook|twitter|linkedin|"
    r"album|actualites|appel.?d.?offres|"
    r"kinshasa|\.cd/|journalofficiel\.cd|presidence\.cd)",
    re.I,
)
TEXT_KEEP_RE = re.compile(
    r"\b(loi|ordonnance|d[eé]cret|decret|constitution|journal\s+officiel|"
    r"code|r[eé]publique\s+du\s+congo|assembl[eé]e\s+nationale|"
    r"pr[eé]sident\s+de\s+la\s+r[eé]publique|promulgue|partie\s+officielle|"
    r"conseil\s+des\s+ministres|brazzaville)\b",
    re.I,
)

SEED_PDFS = [
    # Seeds filled / expanded from live crawl + CDX of official hosts at collect time
]

HOMES = [
    "https://sgg.cg/",
    "https://sgg.cg/fr/accueil.html",
    "https://sgg.cg/en/accueil.html",
    "https://www.sgg.cg/",
    "https://www.primature.gouv.cg/",
    "https://primature.gouv.cg/",
    "https://presidence.cg/",
    "https://www.presidence.cg/",
    "https://assemblee-nationale.cg/",
    "https://www.assemblee-nationale.cg/",
    "https://www.finances.gouv.cg/",
    "https://finances.gouv.cg/",
    "https://gouvernement.cg/",
    "https://justice.gouv.cg/",
    "https://www.justice.gouv.cg/",
]

CDX_PREFIXES = (
    "sgg.cg/",
    "www.sgg.cg/",
    "sgg.gouv.cg/",
    "gouv.cg/",
    "www.gouv.cg/",
    "gouvernement.cg/",
    "www.gouvernement.cg/",
    "primature.gouv.cg/",
    "www.primature.gouv.cg/",
    "presidence.cg/",
    "www.presidence.cg/",
    "presidence.gouv.cg/",
    "assemblee-nationale.cg/",
    "www.assemblee-nationale.cg/",
    "assembleenationale.cg/",
    "finances.gouv.cg/",
    "www.finances.gouv.cg/",
    "economie.gouv.cg/",
    "justice.gouv.cg/",
    "www.justice.gouv.cg/",
    "justice.cg/",
    "journalofficiel.gouv.cg/",
    "journalofficiel.cg/",
    "jo.gouv.cg/",
    "jo.cg/",
)


def _host_ok(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    if any(
        x in host
        for x in (
            "africanlii",
            "congoli",
            "droit-afrique",
            "gazettes.africa",
            "law.africa",
        )
    ):
        return False
    # Never harvest DRC (cd) or CAR (cf) hosts from this collector
    if host.endswith(".cd") or host.endswith(".cf") or "kinshasa" in host:
        return False
    if "journalofficiel.cd" in host or "presidence.cd" in host:
        return False
    return any(host == s or host.endswith("." + s) for s in ALLOWED)


def _norm_url(url: str) -> str:
    url = html_lib.unescape((url or "").split("#")[0].strip())
    if not url:
        return ""
    url = url.replace(":80/", "/").replace(":80?", "?")
    if url.startswith("http://"):
        url = "https://" + url[len("http://") :]
    try:
        p = urlsplit(url)
        host = (p.hostname or "").lower()
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


def _ident_from_url(url: str, title: str | None = None) -> str:
    path = unquote(urlsplit(url).path)
    if title:
        t = re.sub(r"\W+", "-", title).strip("-").lower()[:100]
        if t and len(t) > 8:
            return t
    name = Path(path).name or path
    stem = Path(name).stem
    return re.sub(r"\W+", "-", stem).strip("-").lower()[:160] or re.sub(r"\W+", "-", url)[-80:]


def _is_jo(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    path = unquote(urlsplit(url).path).lower()
    return (
        "journalofficiel" in host
        or host.startswith("jo.")
        or host == "jo.cg"
        or "/jo/" in path
        or "journal-officiel" in path
        or re.search(r"(?i)(jo[-_]?\d|journal.?officiel)", path)
        or ("sgg.cg" in host and re.search(r"(?i)(jo|journal)", path))
    )


def _keep(url: str, title: str | None = None) -> bool:
    if not _host_ok(url):
        return False
    blob = unquote(urlsplit(url).path) + " " + url + " " + (title or "")
    if DROP_RE.search(blob):
        return False
    low = url.lower().split("?")[0]
    if not (low.endswith(".pdf") or "/download" in low or "/document/" in low):
        return False
    if _is_jo(url):
        return True
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


def fetch_cg(url: str, wayback_ts: str | None = None) -> dict:
    got = fetch_official(url, ua=UA, verify=False, min_text=120, wayback=True, wayback_ts=wayback_ts)
    if got.get("status") == "success" and len(got.get("text") or "") >= 120:
        return got
    body = got.get("content") or b""
    if not (isinstance(body, bytes) and body[:4] == b"%PDF"):
        try:
            r = live_get(url, ua=UA, verify=False, timeout=(20, 90), retries=2)
            if getattr(r, "status_code", 0) == 200 and (r.content or b"")[:4] == b"%PDF":
                body = r.content
                got["method"] = "live_pdf"
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


def _add(items, seen, ident, url, ts=None, priority=50, size_hint=None, title=None):
    url = _norm_url(url)
    if not url or not _keep(url, title=title):
        return
    key = url.lower().split("?")[0]
    key2 = key.replace("://www.", "://")
    if key in seen or key2 in seen:
        return
    if size_hint and size_hint > MAX_PDF_BYTES:
        return
    seen.add(key)
    seen.add(key2)
    ident = re.sub(r"\W+", "-", (ident or _ident_from_url(url, title)).strip("-")).lower()[:160]
    items.append((priority, ident, url, ts, size_hint, title))


def discover():
    items = []
    seen = set()

    for seed in SEED_PDFS:
        pri = 5 if "CONSTITUTION" in seed.upper() else 8
        _add(items, seen, _ident_from_url(seed), seed, ts=None, priority=pri)

    for home in HOMES:
        try:
            r = live_get(home, ua=UA, verify=False, timeout=(12, 40), retries=1)
            if getattr(r, "status_code", 0) != 200:
                log.info("home status=%s %s", getattr(r, "status_code", None), home)
                continue
            text = r.text or ""
            n = 0
            for href in re.findall(r'href=["\']([^"\']+)["\']', text, re.I):
                full = urljoin(home, html_lib.unescape(href))
                if ".pdf" in full.lower() or "/download" in full.lower():
                    pri = 15
                    low = unquote(full).lower()
                    if "constitut" in low:
                        pri = 5
                    elif re.search(r"(?i)(loi|ordonnance|code)", low):
                        pri = 10
                    elif _is_jo(full):
                        pri = 12
                    _add(items, seen, _ident_from_url(full), full, ts=None, priority=pri)
                    n += 1
            for href in re.findall(r'(https?://[^\s"\'<>]+\.pdf)', text, re.I):
                _add(items, seen, _ident_from_url(href), href, ts=None, priority=18)
                n += 1
            # shallow crawl of promising subpages (max 8 per home)
            sub = []
            for href in re.findall(r'href=["\']([^"\']+)["\']', text, re.I):
                full = urljoin(home, html_lib.unescape(href))
                if not _host_ok(full):
                    continue
                low = unquote(full).lower()
                if any(
                    k in low
                    for k in (
                        "loi", "jo", "journal", "decret", "code", "constitut",
                        "texte", "document", "download", "upload", "sgg",
                        "legislation", "juridique",
                    )
                ):
                    if full not in sub and not low.endswith(".pdf"):
                        sub.append(full)
            for sub_url in sub[:8]:
                try:
                    r2 = live_get(sub_url, ua=UA, verify=False, timeout=(10, 30), retries=1)
                    if getattr(r2, "status_code", 0) != 200:
                        continue
                    t2 = r2.text or ""
                    for href in re.findall(r'href=["\']([^"\']+)["\']', t2, re.I):
                        full = urljoin(sub_url, html_lib.unescape(href))
                        if ".pdf" in full.lower():
                            pri = 16
                            low = unquote(full).lower()
                            if "constitut" in low:
                                pri = 5
                            elif re.search(r"(?i)(loi|ordonnance|code)", low):
                                pri = 10
                            _add(items, seen, _ident_from_url(full), full, ts=None, priority=pri)
                            n += 1
                except Exception as exc:
                    log.info("sub %s %s", sub_url[:80], exc)
            log.info("home %s links=%s", home, n)
        except Exception as exc:
            log.info("home %s %s", home, exc)

    for prefix in CDX_PREFIXES:
        try:
            hits = cdx_urls(
                prefix,
                limit=env_int("CDX_LIMIT", 200),
                match_type="prefix",
                extra_filters=["statuscode:200", "mimetype:application/pdf"],
            ) or []
        except Exception as exc:
            log.info("cdx %s %s", prefix, exc)
            hits = []
        if len(hits) < 5:
            try:
                hits2 = cdx_urls(
                    prefix,
                    limit=env_int("CDX_LIMIT", 200),
                    match_type="prefix",
                    extra_filters=["statuscode:200"],
                ) or []
                for h in hits2:
                    orig = (h.get("original") or "").lower()
                    if ".pdf" in orig:
                        hits.append(h)
            except Exception as exc:
                log.info("cdx2 %s %s", prefix, exc)
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
            low = unquote(orig).lower()
            if "constitut" in low:
                pri = 5
            elif _is_jo(orig):
                pri = 14
            elif re.search(r"(?i)(loi|ordonnance|code)", low):
                pri = 12
            elif re.search(r"(?i)(decret|d[eé]cret|arrete)", low):
                pri = 20
            _add(items, seen, _ident_from_url(orig), orig, ts=ts, priority=pri, size_hint=length or None)

    items.sort(key=lambda x: (x[0], x[1]))
    out = [(ident, url, ts, size, title) for _, ident, url, ts, size, title in items]
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
    for ident, url, ts, size_hint, title in discover():
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
        # hard safety: never save DRC hosts
        if not _host_ok(url):
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "host_not_cg"})
            continue
        got = fetch_cg(url, wayback_ts=ts)
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
        if not TEXT_KEEP_RE.search(text[:8000]) and not _is_jo(url):
            if not re.search(r"(?i)(loi|ordonnance|decret|constitut|code|jo-)", ident):
                fail += 1
                log_failure(CC, {"identifier": ident, "source_url": url, "reason": "text_not_legal"})
                continue
        use_title = title
        if not use_title:
            for line in text.splitlines():
                if len(line.strip()) > 18:
                    use_title = line.strip()[:240]
                    break
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=use_title or ident, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_cg.py",
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
        source="Republic of the Congo / Congo-Brazzaville (sgg.cg / Primature / Présidence / AN / Finances / JO)",
        source_urls=[
            "https://sgg.cg/",
            "https://www.primature.gouv.cg/",
            "https://presidence.cg/",
            "https://assemblee-nationale.cg/",
            "https://www.finances.gouv.cg/",
            "https://gouvernement.cg/",
            "https://justice.gouv.cg/",
        ],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (live crawl *.gouv.cg / *.cg + CDX PDF / JO)",
        notes=(
            "Official *.cg / *.gouv.cg JO/SGG/justice/primature PDFs only (Congo-Brazzaville). "
            "OCR fra for scans. Not AfricanLII. No WAF bypass. Not legal advice. "
            "cg=Congo-Brazzaville (not DRC/cd, not CAR/cf)."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s total_instruments=%s", ok, skip, fail, len(done))


if __name__ == "__main__":
    main()
