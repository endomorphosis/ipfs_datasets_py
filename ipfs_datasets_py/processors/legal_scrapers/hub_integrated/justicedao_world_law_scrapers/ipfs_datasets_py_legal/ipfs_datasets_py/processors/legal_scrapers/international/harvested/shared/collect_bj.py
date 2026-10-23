#!/usr/bin/env python3
"""Benin (bj): official law PDFs from SGG documenthèque + related *.gouv.bj hosts.

Official only:
  - https://sgg.gouv.bj/documentheque/ (lois / décrets / ordonnances / arrêtés)
  - https://sgg.gouv.bj/doc/<slug>/download  (live PDF; often scanned → OCR fra)
  - https://www.gouv.bj/doc/<id>/download   (portal mirrors; CDX)
  - https://justice.gouv.bj/doc/<id>/download (CDX; live often 503)
  - https://journalofficiel.gouv.bj/        (portal shell; CDX thin)
  - Assemblée nationale / Cour constitutionnelle *.bj when official PDFs

Filter: prefer loi/ordonnance/constitution/code; skip PDFs >12MB; JO fascicules OK.
Not AfricanLII / Droit-Afrique. No WAF bypass. Not legal advice.
"""
from __future__ import annotations

import logging
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

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

CC, COUNTRY, LANG = "bj", "Benin", "fr"
SOURCE_TYPE = "sgg_benin_documentheque"
LICENSE = (
    "République du Bénin — Secrétariat général du Gouvernement (sgg.gouv.bj) / "
    "Portail du Gouvernement (gouv.bj) / Journal Officiel (journalofficiel.gouv.bj) / "
    "Ministère de la Justice (justice.gouv.bj) / Assemblée nationale. "
    "Authentic Journal Officiel / official text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://sgg.gouv.bj/)"
ART = re.compile(r"(?im)^\s*((?:Article|Art\.?)\s+\d+[a-zA-Zº°]?)\b")
log = logging.getLogger("bj")

SGG = "https://sgg.gouv.bj"
MAX_PDF_BYTES = 12 * 1024 * 1024

ALLOWED = (
    "sgg.gouv.bj",
    "gouv.bj",
    "journalofficiel.gouv.bj",
    "justice.gouv.bj",
    "primature.gouv.bj",
    "finances.gouv.bj",
    "economie.gouv.bj",
    "assemblee-nationale.bj",
    "courconstitutionnelle.bj",
    "presidence.bj",
    "gov.bj",
)

KEEP_RE = re.compile(
    r"(loi|ordonnance|ordonn|d[eé]cret|decret|arr[eê]t[eé]|arrete|constitution|code|"
    r"journal.?officiel|\bjo\b|organique|r[eè]glement|charte|statut|"
    r"documentheque|/doc/)",
    re.I,
)
DROP_RE = re.compile(
    r"(africanlii|beninlii|droit-afrique|gazettes\.africa|law\.africa|"
    r"discours|allocution|communique|photo|banner|logo|cv[-_]|"
    r"biographie|rapport[-_ ]annuel|presentation|organigramme|"
    r"audiences?_roles?|newsletter|recrutement|facebook|twitter|linkedin|"
    r"/cm/\d{4}-\d{2}-\d{2}/|"  # conseil des ministres comptes rendus
    r"documentation-anbenin)",
    re.I,
)
TEXT_KEEP_RE = re.compile(
    r"\b(loi|ordonnance|d[eé]cret|decret|constitution|journal\s+officiel|"
    r"code|r[eé]publique\s+du\s+b[eé]nin|assembl[eé]e\s+nationale|"
    r"pr[eé]sident\s+de\s+la\s+r[eé]publique|promulgue)\b",
    re.I,
)

LISTINGS = [
    # (path_prefix, max_pages, priority)
    ("lois", 8, 10),
    ("ordonnances", 4, 20),
    ("decrets", 2, 40),
    ("arretes", 1, 50),
    ("decisions", 1, 55),
    ("accords", 1, 60),
]

SEED_DOWNLOADS = [
    # Constitution revision 2019 (text PDF)
    "https://sgg.gouv.bj/doc/loi-2019-40/download",
    "https://sgg.gouv.bj/doc/loi-2019-43/download",  # code électoral
    "https://sgg.gouv.bj/doc/loi-2019-41/download",
    "https://sgg.gouv.bj/doc/loi-2019-45/download",
]


def _host_ok(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    if any(x in host for x in ("africanlii", "beninlii", "droit-afrique", "gazettes.africa", "law.africa")):
        return False
    return any(host == s or host.endswith("." + s) for s in ALLOWED)


def _norm_url(url: str) -> str:
    url = (url or "").split("#")[0].strip()
    if not url:
        return ""
    if url.startswith("http://"):
        url = "https://" + url[len("http://") :]
    url = re.sub(r"(https?://[^/:]+):80/", r"\1/", url)
    # Prefer /download over /read for same slug
    url = re.sub(r"/read/?$", "/download", url)
    return url


def _parse_size_bytes(label: str | None) -> int | None:
    if not label:
        return None
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(Ko|Mo|Go|KB|MB|GB)", label, re.I)
    if not m:
        return None
    n = float(m.group(1).replace(",", "."))
    unit = m.group(2).lower()
    mult = {"ko": 1024, "kb": 1024, "mo": 1024**2, "mb": 1024**2, "go": 1024**3, "gb": 1024**3}[unit]
    return int(n * mult)


def _ident_from_url(url: str) -> str:
    path = unquote(urlsplit(url).path)
    m = re.search(r"/doc/([^/]+)/(?:download|read)?/?$", path, re.I)
    if m:
        return re.sub(r"\W+", "-", m.group(1)).strip("-").lower()[:160]
    name = Path(path).name or path
    return re.sub(r"\W+", "-", name).strip("-").lower()[:160]


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


def fetch_bj(url: str, wayback_ts: str | None = None) -> dict:
    """Live-first official fetch; OCR scanned SGG PDFs when pdftotext is empty."""
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
    log.info("OCR fra %s bytes=%s", url.split("/")[-2][:40] if "/doc/" in url else url[-40:], len(body))
    ocr = ocr_pdf(body)
    if len(ocr) >= 120:
        got.update(status="success", text=ocr, content=body, method="ocr_fra")
        return got
    got["error"] = (got.get("error") or "") + ";ocr_short"
    return got


def _add(items, seen, ident, url, ts=None, priority=50, size_hint=None):
    url = _norm_url(url)
    if not url or not _host_ok(url):
        return
    if DROP_RE.search(url):
        return
    blob = unquote(url)
    if not KEEP_RE.search(blob):
        return
    # Prefer download endpoints
    if "/doc/" in url and not url.rstrip("/").endswith("/download") and not url.lower().endswith(".pdf"):
        if url.rstrip("/").endswith("/read"):
            url = url.rstrip("/")[:-5] + "/download"
        elif re.search(r"/doc/[^/]+/?$", url):
            url = url.rstrip("/") + "/download"
    key = url.lower().split("?")[0]
    if key in seen:
        return
    if size_hint and size_hint > MAX_PDF_BYTES:
        return
    seen.add(key)
    ident = re.sub(r"\W+", "-", (ident or _ident_from_url(url)).strip("-")).lower()[:160]
    items.append((priority, ident, url, ts, size_hint))


def _listing_cards(html: str, base: str):
    """Yield (slug, title, size_bytes) from SGG documenthèque HTML."""
    # Size label sits near each /doc/<slug>/ block
    for m in re.finditer(
        r"<b class='semibold'>(\d+(?:[.,]\d+)?\s*(?:Ko|Mo|Go))</b>.*?/doc/([a-z0-9\-]+)/",
        html,
        re.I | re.S,
    ):
        size = _parse_size_bytes(m.group(1))
        slug = m.group(2)
        title_m = re.search(
            rf"/doc/{re.escape(slug)}/[^>]*>\s*([^<]+)",
            html[m.start() : m.start() + 2500],
            re.I,
        )
        title = (title_m.group(1).strip() if title_m else slug)
        yield slug, title, size
    # Fallback: any /doc/slug/download
    for slug in set(re.findall(r"/doc/([a-z0-9\-]+)/download", html, re.I)):
        yield slug, slug, None


def discover():
    items = []
    seen = set()

    for seed in SEED_DOWNLOADS:
        _add(items, seen, _ident_from_url(seed), seed, ts=None, priority=5)

    for kind, max_pages, pri in LISTINGS:
        for page in range(1, max_pages + 1):
            if page == 1:
                url = f"{SGG}/documentheque/{kind}/"
            else:
                url = f"{SGG}/documentheque/{kind}/{page}/"
            try:
                r = live_get(url, ua=UA, verify=False, timeout=(15, 45), retries=2)
                if getattr(r, "status_code", 0) != 200:
                    continue
                html = r.text or ""
                n = 0
                for slug, title, size in _listing_cards(html, url):
                    if not re.search(r"(loi|ordonnance|decret|d[eé]cret|arrete|arr[eê]t|decision|accord|code)", slug, re.I):
                        continue
                    # Prefer substantive instruments over raw accords for lean harvest
                    p = pri
                    if slug.startswith("loi"):
                        p = 10
                    elif slug.startswith("ordonnance"):
                        p = 20
                    elif "constit" in (title or "").lower() or "constit" in slug:
                        p = 5
                    dl = f"{SGG}/doc/{slug}/download"
                    _add(items, seen, slug, dl, ts=None, priority=p, size_hint=size)
                    n += 1
                log.info("listing %s page=%s cards=%s", kind, page, n)
                if n == 0 and page > 1:
                    break
            except Exception as exc:
                log.info("listing %s %s", url, exc)

    # Live crawl a few SGG / gouv / AN homes for stray PDF links
    homes = [
        f"{SGG}/",
        f"{SGG}/documentheque/",
        "https://www.gouv.bj/",
        "https://journalofficiel.gouv.bj/",
        "https://www.assemblee-nationale.bj/",
        "https://assemblee-nationale.bj/index.php/repertoire-des-lois/lois-votees/repertoire-des-lois-votees/",
        "https://courconstitutionnelle.bj/",
    ]
    for home in homes:
        try:
            r = live_get(home, ua=UA, verify=False, timeout=(12, 40), retries=1)
            if getattr(r, "status_code", 0) != 200:
                continue
            text = r.text or ""
            for href in re.findall(r'href=["\']([^"\']+)["\']', text, re.I):
                full = urljoin(home, href.replace("&amp;", "&"))
                if ".pdf" in full.lower() or "/doc/" in full.lower():
                    _add(items, seen, _ident_from_url(full), full, ts=None, priority=35)
            for href in re.findall(r'(https?://[^\s"\'<>]+\.pdf)', text, re.I):
                _add(items, seen, _ident_from_url(href), href, ts=None, priority=35)
        except Exception as exc:
            log.info("home %s %s", home, exc)

    cdx_prefixes = (
        "sgg.gouv.bj/doc/loi-",
        "sgg.gouv.bj/doc/ordonnance-",
        "sgg.gouv.bj/doc/decret-",
        "sgg.gouv.bj/doc/arrete-",
        "www.gouv.bj/doc/",
        "gouv.bj/doc/",
        "justice.gouv.bj/doc/",
        "www.justice.gouv.bj/doc/",
        "journalofficiel.gouv.bj/",
        "assemblee-nationale.bj/",
        "www.assemblee-nationale.bj/",
    )
    for prefix in cdx_prefixes:
        try:
            hits = cdx_urls(
                prefix,
                limit=env_int("CDX_LIMIT", 220),
                match_type="prefix",
                extra_filters=["statuscode:200"],
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
            path = unquote(urlsplit(orig).path).lower()
            # Keep download endpoints and .pdf; skip HTML shells and /read duplicates later via norm
            if "/doc/" in path and not (path.rstrip("/").endswith("/download") or path.endswith(".pdf")):
                if path.rstrip("/").endswith("/read") or re.search(r"/doc/[^/]+/?$", path):
                    pass  # _add will normalize to /download
                else:
                    continue
            if DROP_RE.search(orig):
                continue
            if not KEEP_RE.search(unquote(orig)) and ".pdf" not in orig.lower():
                continue
            pri = 25
            if re.search(r"(?i)/doc/loi-", orig):
                pri = 12
            elif re.search(r"(?i)/doc/ordonnance-", orig):
                pri = 18
            elif re.search(r"(?i)constitut", orig):
                pri = 8
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
        got = fetch_bj(url, wayback_ts=ts)
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
        # Soft content filter for non-loi CDX noise
        if not TEXT_KEEP_RE.search(text[:4000]) and not re.search(r"(?i)^(loi|ordonnance|decret)", ident):
            # still keep if URL clearly a loi/ordonnance
            if not re.search(r"(?i)/doc/(loi|ordonnance|decret|arrete)-", url):
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
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_bj.py",
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
        source="Benin SGG documenthèque / gouv.bj / justice.gouv.bj / Journal Officiel",
        source_urls=[
            "https://sgg.gouv.bj/documentheque/",
            "https://sgg.gouv.bj/documentheque/lois/",
            "https://www.gouv.bj/",
            "https://journalofficiel.gouv.bj/",
            "https://justice.gouv.bj/",
        ],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (SGG documenthèque live lois/ordonnances/décrets + CDX *.gouv.bj /doc/)",
        notes="Official *.gouv.bj / Assemblée nationale PDFs only. OCR fra for scans. Not AfricanLII. No WAF bypass. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s total_instruments=%s", ok, skip, fail, len(done))


if __name__ == "__main__":
    main()
