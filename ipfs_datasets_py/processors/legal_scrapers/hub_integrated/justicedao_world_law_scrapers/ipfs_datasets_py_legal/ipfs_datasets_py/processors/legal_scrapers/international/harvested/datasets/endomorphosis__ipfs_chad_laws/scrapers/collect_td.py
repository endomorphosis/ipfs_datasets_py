#!/usr/bin/env python3
"""Chad / Tchad (td): official law / JO PDFs from journalofficiel.td + *.gouv.td / *.td.

Official only:
  - https://journalofficiel.td/  (SGG Journal Officiel — public REST pl_journaux / pl_textes
    + /storage/v1/object/public/archiva/{journaux,textes}/*.pdf live)
  - https://presidence.td/wp-content/uploads/ (Constitution / décrets / arrêtés — CDX; live often 403)
  - https://finances.gouv.td/ (lois de finances / CGI / décrets — CDX K2 downloads + path PDFs; live often 503)
  - primature.gouv.td / sgg.gouv.td / justice.gouv.td / assemblee-nationale.td when PDF (CDX)
  - Wayback/CDX of the same official *.td / *.gouv.td / *.gov.td URLs

Filter: JO fascicules kept; textes require loi/ordonnance/décret/constitution/code;
skip PDFs >12MB; drop biographies / communiqués / organigrammes.
Not AfricanLII / Droit-Afrique. No WAF bypass. Not legal advice.
NOTE: country code td = Chad / Tchad.
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

CC, COUNTRY, LANG = "td", "Chad", "fr"
SOURCE_TYPE = "jo_chad_official"
LICENSE = (
    "République du Tchad — Journal Officiel (journalofficiel.td / SGG) / "
    "Présidence (presidence.td) / Ministère des Finances (finances.gouv.td) / "
    "Primature / Justice / Assemblée nationale. "
    "Authentic Journal Officiel / official text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://journalofficiel.td/; Chad=td)"
ART = re.compile(r"(?im)^\s*((?:Article|Art\.?)\s+\d+[a-zA-Zº°]?)\b")
log = logging.getLogger("td")

JO = "https://journalofficiel.td"
PRESIDENCE = "https://presidence.td"
FINANCES = "https://finances.gouv.td"
MAX_PDF_BYTES = 12 * 1024 * 1024

ALLOWED = (
    "journalofficiel.td",
    "www.journalofficiel.td",
    "presidence.td",
    "www.presidence.td",
    "finances.gouv.td",
    "www.finances.gouv.td",
    "primature.gouv.td",
    "www.primature.gouv.td",
    "sgg.gouv.td",
    "www.sgg.gouv.td",
    "justice.gouv.td",
    "www.justice.gouv.td",
    "justice.td",
    "gouv.td",
    "gov.td",
    "assemblee-nationale.td",
    "www.assemblee-nationale.td",
    "assembleenationale.td",
    "an.td",
    "inseed.td",
    "www.inseed.td",
)

KEEP_RE = re.compile(
    r"(loi|ordonnance|ordonn|d[eé]cret|decret|arr[eê]t[eé]|arrete|constitution|code|"
    r"journal.?officiel|\bjos?\b|\bjo\b|organique|r[eè]glement|charte|statut|"
    r"/archiva/journaux/|/archiva/textes/|/wp-content/uploads/|"
    r"item/download|decrets_arretes|cgi|impot|budget)",
    re.I,
)
DROP_RE = re.compile(
    r"(africanlii|tchadlii|droit-afrique|gazettes\.africa|law\.africa|"
    r"discours|allocution|communique|photo|banner|logo|cv[-_]|"
    r"biographie|rapport[-_ ]annuel|presentation|organigramme|"
    r"newsletter|recrutement|facebook|twitter|linkedin|"
    r"album|actualites|/archiva/communiques/|/archiva/discours/|"
    r"/archiva/magazines/|/archiva/publications/|"
    r"gouv_connect|magazine.?sp[eé]cial|fia-?2025|"
    r"dsf_|etats.?financiers|oil.?revenue|conjoncture)",
    re.I,
)
TEXT_KEEP_RE = re.compile(
    r"\b(loi|ordonnance|d[eé]cret|decret|constitution|journal\s+officiel|"
    r"code|r[eé]publique\s+du\s+tchad|assembl[eé]e\s+nationale|"
    r"pr[eé]sident\s+de\s+la\s+r[eé]publique|promulgue|partie\s+officielle|"
    r"conseil\s+des\s+ministres)\b",
    re.I,
)

SEED_PDFS = [
    # Constitution 2018 (presidence — CDX/live)
    "https://presidence.td/wp-content/uploads/2020/03/CONSTITUTION-DE-LA-REPUBLIQUE-PROMULGUEE-04-MAI-2018.pdf",
    # Known recent JO fascicule (live storage)
    "https://journalofficiel.td/storage/v1/object/public/archiva/journaux/2026/03/1781082767125-u3kjg7dihcg.pdf",
]

# Public client anon JWT is embedded in journalofficiel.td Next.js bundles (role=anon).
# Prefer discovering it live; fall back to the published client key.
_ANON_FALLBACK = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJyb2xlIjoiYW5vbiIsImlzcyI6InN1cGFiYXNlIiwiaWF0IjoxNzg2OTExNzEzLCJleHAiOjIxMDIyNzE3MTN9."
    "JkWAV0Loj56XIPGAteIDCDsC747tx9MIQeu5x4Ekjpc"
)


def _host_ok(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    if any(x in host for x in ("africanlii", "tchadlii", "droit-afrique", "gazettes.africa", "law.africa")):
        return False
    return any(host == s or host.endswith("." + s) for s in ALLOWED)


def _norm_url(url: str) -> str:
    url = html_lib.unescape((url or "").split("#")[0].strip())
    if not url:
        return ""
    url = url.replace(":80/", "/").replace(":80?", "?")
    if url.startswith("http://"):
        url = "https://" + url[len("http://") :]
    if url.startswith("/"):
        url = JO + url
    try:
        p = urlsplit(url)
        host = (p.hostname or "").lower()
        if host == "www.journalofficiel.td":
            host = "journalofficiel.td"
        if host == "www.presidence.td":
            host = "presidence.td"
        if host == "www.finances.gouv.td":
            host = "finances.gouv.td"
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
    if "/archiva/journaux/" in path:
        # jo-YYYY-MM-<stem>
        m = re.search(r"/journaux/(\d{4})/(\d{2})/([^/]+)$", path)
        if m:
            stem = re.sub(r"\W+", "", Path(m.group(3)).stem)[:24].lower()
            return f"jo-{m.group(1)}-{m.group(2)}-{stem}"
    if "/archiva/textes/" in path:
        stem = re.sub(r"\W+", "-", Path(path).stem).strip("-").lower()[:100]
        return f"texte-{stem}"
    if "/item/download/" in path:
        slug = path.rstrip("/").split("/item/download/")[-1]
        return "fin-" + re.sub(r"\W+", "-", slug).strip("-").lower()[:120]
    if title:
        t = re.sub(r"\W+", "-", title).strip("-").lower()[:100]
        if t:
            return t
    name = Path(path).name or path
    stem = Path(name).stem
    return re.sub(r"\W+", "-", stem).strip("-").lower()[:160] or re.sub(r"\W+", "-", url)[-80:]


def _is_jo(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    path = unquote(urlsplit(url).path).lower()
    return "journalofficiel.td" in host and (
        "/archiva/journaux/" in path or "/archiva/textes/" in path or path.endswith(".pdf")
    )


def _keep(url: str, title: str | None = None) -> bool:
    if not _host_ok(url):
        return False
    blob = unquote(urlsplit(url).path) + " " + url + " " + (title or "")
    if DROP_RE.search(blob):
        return False
    if not url.lower().split("?")[0].endswith(".pdf") and "/item/download/" not in urlsplit(url).path:
        # allow K2 downloads without .pdf suffix
        if "/item/download/" not in urlsplit(url).path:
            return False
    if _is_jo(url) and "/archiva/journaux/" in unquote(urlsplit(url).path).lower():
        return True
    if "/archiva/textes/" in unquote(urlsplit(url).path).lower():
        return bool(KEEP_RE.search(blob))
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


def fetch_td(url: str, wayback_ts: str | None = None) -> dict:
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
    if key in seen:
        return
    if size_hint and size_hint > MAX_PDF_BYTES:
        return
    seen.add(key)
    ident = re.sub(r"\W+", "-", (ident or _ident_from_url(url, title)).strip("-")).lower()[:160]
    items.append((priority, ident, url, ts, size_hint, title))


def _jo_anon_key() -> str:
    """Discover public Supabase anon JWT from journalofficiel.td client bundles."""
    try:
        r = live_get(f"{JO}/fr", ua=UA, verify=False, timeout=(15, 40), retries=2)
        html = r.text or ""
        chunks = sorted(set(re.findall(r"/_next/static/chunks/[a-zA-Z0-9._-]+\.js", html)))
        blob = html
        for path in chunks[:18]:
            try:
                cr = live_get(JO + path, ua=UA, verify=False, timeout=(12, 30), retries=1)
                if getattr(cr, "status_code", 0) == 200 and cr.text:
                    blob += cr.text
            except Exception:
                continue
        m = re.search(
            r"(eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)",
            blob,
        )
        if m:
            return m.group(1)
    except Exception as exc:
        log.info("anon discover: %s", exc)
    return _ANON_FALLBACK


def _rest_rows(table: str, anon: str, params: str, limit: int = 100) -> list[dict]:
    """Page public PostgREST on journalofficiel.td (official site API)."""
    out: list[dict] = []
    offset = 0
    while offset < limit:
        page = min(100, limit - offset)
        url = f"{JO}/rest/v1/{table}?{params}&limit={page}&offset={offset}"
        try:
            # use curl-equivalent via live_get with headers — requests Session in live_get
            import requests

            r = requests.get(
                url,
                headers={
                    "apikey": anon,
                    "Authorization": f"Bearer {anon}",
                    "Accept": "application/json",
                    "User-Agent": UA,
                },
                timeout=45,
                verify=False,
            )
            if r.status_code not in (200, 206):
                log.info("rest %s offset=%s status=%s", table, offset, r.status_code)
                break
            rows = r.json()
            if not isinstance(rows, list) or not rows:
                break
            out.extend(rows)
            if len(rows) < page:
                break
            offset += len(rows)
        except Exception as exc:
            log.info("rest %s %s", table, exc)
            break
    return out


def discover():
    items = []
    seen = set()

    for seed in SEED_PDFS:
        pri = 5 if "CONSTITUTION" in seed.upper() else 8
        _add(items, seen, _ident_from_url(seed), seed, ts=None, priority=pri)

    anon = _jo_anon_key()
    log.info("JO anon key len=%s", len(anon or ""))

    # Official JO fascicules (prefer recent years)
    journaux = _rest_rows(
        "pl_journaux",
        anon,
        "select=id,titre,annee,numero,type,pdf_url,date_publication"
        "&pdf_url=not.is.null&order=annee.desc,id.desc",
        limit=env_int("JO_REST_LIMIT", 200),
    )
    for row in journaux:
        pdf = row.get("pdf_url") or ""
        year = row.get("annee") or 0
        try:
            year = int(year)
        except Exception:
            year = 0
        if year < 1958 or year > 2100:
            continue
        title = row.get("titre") or f"JO {year}-{row.get('numero')}"
        pri = 15
        if year >= 2024:
            pri = 10
        elif year >= 2018:
            pri = 14
        elif year >= 2000:
            pri = 22
        else:
            pri = 35
        if (row.get("type") or "").lower() == "special":
            pri = min(pri, 12)
        _add(
            items, seen,
            _ident_from_url(pdf, title) if pdf else f"jo-{row.get('id')}",
            pdf, ts=None, priority=pri, title=title,
        )

    # Individual consolidated textes (lois / codes / ordonnances)
    textes = _rest_rows(
        "pl_textes",
        anon,
        "select=id,titre,type,pdf_url,annee,date_publication"
        "&pdf_url=not.is.null&order=annee.desc,id.desc",
        limit=env_int("TEXTES_REST_LIMIT", 80),
    )
    for row in textes:
        pdf = row.get("pdf_url") or ""
        title = row.get("titre") or ""
        typ = (row.get("type") or "") + " " + title
        if re.search(r"(?i)port[eé]e\s+individuelle|avancement|nomination|mle\s+\d", typ):
            continue
        pri = 12
        if re.search(r"(?i)constitut|code|loi\s*n|ordonnance", typ):
            pri = 6
        _add(items, seen, _ident_from_url(pdf, title), pdf, ts=None, priority=pri, title=title)

    # Also /api/documents lean (may include demo rows — text filter later)
    try:
        r = live_get(f"{JO}/api/documents", ua=UA, verify=False, timeout=(15, 40), retries=2)
        if getattr(r, "status_code", 0) == 200:
            docs = r.json()
            if isinstance(docs, list):
                for d in docs:
                    pdf = d.get("pdf_url") or ""
                    title = d.get("titre") or ""
                    nature = d.get("natureTexte") or ""
                    if not pdf:
                        continue
                    if DROP_RE.search(pdf + " " + title):
                        continue
                    if not KEEP_RE.search(pdf + " " + title + " " + nature):
                        continue
                    _add(items, seen, _ident_from_url(pdf, title), pdf, priority=40, title=title)
    except Exception as exc:
        log.info("api/documents %s", exc)

    cdx_prefixes = (
        "presidence.td/wp-content/uploads/",
        "www.presidence.td/wp-content/uploads/",
        "finances.gouv.td/images/",
        "www.finances.gouv.td/images/",
        "finances.gouv.td/index.php/component/k2/item/download/",
        "www.finances.gouv.td/index.php/component/k2/item/download/",
        "journalofficiel.td/storage/v1/object/public/archiva/journaux/",
        "journalofficiel.td/storage/v1/object/public/archiva/textes/",
        "primature.gouv.td/",
        "sgg.gouv.td/",
        "justice.gouv.td/",
        "assemblee-nationale.td/",
    )
    for prefix in cdx_prefixes:
        try:
            hits = cdx_urls(
                prefix,
                limit=env_int("CDX_LIMIT", 180),
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
            low = unquote(orig).lower()
            if "constitut" in low:
                pri = 5
            elif "/archiva/journaux/" in low:
                pri = 18
            elif "/archiva/textes/" in low or re.search(r"(?i)(loi|code|ordonnance)", low):
                pri = 16
            elif "presidence.td" in low and re.search(r"(?i)(decret|arrete|loi)", low):
                pri = 20
            elif "finances.gouv.td" in low:
                # finances CDX is noisy — lower priority; text filter later
                if re.search(r"(?i)(loi|decret|ordonnance|cgi|code|organique|budget)", low):
                    pri = 24
                else:
                    pri = 45
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
        got = fetch_td(url, wayback_ts=ts)
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
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_td.py",
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
        source="Chad Journal Officiel (journalofficiel.td) / Présidence / Finances",
        source_urls=[
            "https://journalofficiel.td/",
            "https://journalofficiel.td/fr/journal-officiel/ordinaire",
            "https://journalofficiel.td/fr/textes/all",
            "https://presidence.td/",
            "https://finances.gouv.td/",
        ],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (journalofficiel.td REST pl_journaux/pl_textes live + storage PDFs; presidence/finances CDX; live CF/503 on some hosts)",
        notes="Official *.td / *.gouv.td / JO PDFs only. OCR fra for scans. Not AfricanLII. No WAF bypass. Not legal advice. td=Chad/Tchad.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s total_instruments=%s", ok, skip, fail, len(done))


if __name__ == "__main__":
    main()
