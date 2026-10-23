#!/usr/bin/env python3
"""Cabo Verde / Cape Verde (cv): official Boletim Oficial + law texts from *.cv / *.gov.cv.

Official only (Portuguese primary):
  - https://boe.incv.cv/  (Imprensa Nacional — BOE / Boletim Oficial; /api/v1)
  - https://incv.cv/ / kiosk.incv.cv (redirects to boe.incv.cv)
  - https://www.governo.cv/ / governo.cv
  - https://www.parlamento.cv/ / parlamento.cv (Assembleia Nacional)
  - https://justica.gov.cv/ / www.justica.gov.cv
  - https://www.mf.gov.cv/ / mf.gov.cv (Finanças)
  - https://www.gov.cv/ / gov.cv
  - https://www.bcv.cv/ / https://www.ine.cv/
  - https://www.tribunalconstitucional.cv/
  - Wayback/CDX of the same official *.cv / *.gov.cv URLs

Filter: prefer lei/decreto/constituição/código/Boletim; skip PDFs >12MB.
Not AfricanLII / Droit-Afrique. No WAF bypass. Not legal advice.
NOTE: Leave Lesotho / Eswatini / Burundi / Portugal alone.
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
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote, unquote, urlencode, urljoin, urlsplit, urlunsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, html_to_text, http_get, log_failure, utcnow, write_summary
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

CC, COUNTRY, LANG = "cv", "Cabo Verde", "pt"
SOURCE_TYPE = "caboverde_official_boletim_oficial_laws"
LICENSE = (
    "República de Cabo Verde — Imprensa Nacional / Boletim Oficial (boe.incv.cv / incv.cv) / "
    "Portal do Governo (governo.cv) / Assembleia Nacional (parlamento.cv) / "
    "Justiça (justica.gov.cv) / Finanças (mf.gov.cv) / gov.cv / BCV / INE / "
    "Tribunal Constitucional and other *.cv / *.gov.cv gazette hosts. Authentic Boletim "
    "Oficial / official text prevails. Not legal advice. Not Portugal (pt) / Angola (ao) / "
    "São Tomé (st)."
)
UA = (
    "legal-corpora-collector/1.0 (research; source=https://boe.incv.cv/; "
    "CaboVerde=cv not pt/ao/st)"
)
ART = re.compile(
    r"(?im)^\s*((?:Artigo|Art\.?|Secção|Secao|Capítulo|Capitulo|Cap\.?|"
    r"Título|Titulo|Parte|Disposição|Disposicao)\s*[IVXLC0-9º°a-zA-Z]*)\b"
)
log = logging.getLogger("cv")

MAX_PDF_BYTES = 12 * 1024 * 1024
API = "https://boe.incv.cv/api/v1"
API_HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json",
    "Ankira-App-Version": "1.0.0",
}

ALLOWED = (
    "boe.incv.cv",
    "incv.cv",
    "www.incv.cv",
    "kiosk.incv.cv",
    "governo.cv",
    "www.governo.cv",
    "parlamento.cv",
    "www.parlamento.cv",
    "assembleianacional.cv",
    "www.assembleianacional.cv",
    "presidencia.cv",
    "www.presidencia.cv",
    "gov.cv",
    "www.gov.cv",
    "justica.gov.cv",
    "www.justica.gov.cv",
    "mf.gov.cv",
    "www.mf.gov.cv",
    "bcv.cv",
    "www.bcv.cv",
    "ine.cv",
    "www.ine.cv",
    "tribunalconstitucional.cv",
    "www.tribunalconstitucional.cv",
    "stj.cv",
    "www.stj.cv",
    "pgr.cv",
    "www.pgr.cv",
    "anac.cv",
    "www.anac.cv",
    "are.cv",
    "www.are.cv",
)

KEEP_RE = re.compile(
    r"(lei|leis|decreto|diploma|resolu[cç][aã]o|proclama|"
    r"constitui[cç][aã]o|regulamento|portaria|despacho|"
    r"boletim|oficial|gazette|jornal|"
    r"legislacao|legisla[cç][aã]o|normativo|estatuto|codigo|c[oó]digo|"
    r"amendment|altera[cç][aã]o|lei[_/\-]|decreto[_/\-]|"
    r"wp-content/uploads|/uploads/|/files/|/documents?/|/ficheiros?/|"
    r"cabo.?verde|cape.?verde|/Bulletins/Download/)",
    re.I,
)
DROP_RE = re.compile(
    r"(africanlii|droit-afrique|gazettes\.africa|law\.africa|"
    r"discurso|allocution|communique|comunicado|nota.?de.?prensa|photo|banner|logo|"
    r"biograf|organigrama|presentacion|newsletter|"
    r"facebook|twitter|linkedin|album|actualites|licitacao|"
    r"favicon|apple-touch|webmanifest|/css/|\.css\b|"
    r"portugal|\.pt/|dre\.pt|diariodarepublica|"
    r"angola|\.ao/|sao.?tome|\.st/|lesotho|eswatini|burundi)",
    re.I,
)
TEXT_KEEP_RE = re.compile(
    r"\b(lei|decreto|diploma|constitui[cç][aã]o|boletim\s+oficial|"
    r"c[oó]digo|rep[uú]blica\s+de\s+cabo\s+verde|"
    r"assembleia\s+nacional|presidente\s+da\s+rep[uú]blica|promulga|"
    r"artigo|cabo\s+verde|resolu[cç][aã]o|regulamento|ac[oó]rd[aã]o)\b",
    re.I,
)

ACT_QUERIES = [
    "constituição",
    "código civil",
    "código penal",
    "código comercial",
    "código do trabalho",
    "decreto-lei",
    "decreto legislativo",
    "Lei n.º",
    "Lei Orgânica",
    "Assembleia Nacional",
    "regulamento",
    "estatuto",
    "portaria",
    "resolução",
    "Banco de Cabo Verde",
    "Tribunal Constitucional",
    "Código da Propriedade Industrial",
    "regime jurídico",
]

HOMES = [
    "https://boe.incv.cv/",
    "https://incv.cv/",
    "https://incv.cv/boletim-oficial/",
    "https://www.governo.cv/",
    "https://www.governo.cv/documentos/",
    "https://www.parlamento.cv/",
    "https://www.parlamento.cv/legislacao.php",
    "https://justica.gov.cv/",
    "https://justica.gov.cv/legisla%C3%A7%C3%B5es",
    "https://www.mf.gov.cv/",
    "https://www.gov.cv/",
    "https://www.gov.cv/legislacao",
    "https://www.gov.cv/lei-justica",
    "https://www.bcv.cv/",
    "https://www.bcv.cv/pt/O%20Banco/Constituicao%20da%20Republica/Paginas/ConstituicaodaRepublica.aspx",
    "https://www.bcv.cv/pt/O%20Banco/Lei%20Organica/Paginas/LeiOrganica.aspx",
    "https://www.ine.cv/",
    "https://www.tribunalconstitucional.cv/",
]

CDX_PREFIXES = (
    "boe.incv.cv/",
    "incv.cv/",
    "www.incv.cv/",
    "www.governo.cv/",
    "governo.cv/",
    "www.parlamento.cv/",
    "parlamento.cv/",
    "justica.gov.cv/",
    "www.justica.gov.cv/",
    "www.mf.gov.cv/",
    "mf.gov.cv/",
    "www.gov.cv/",
    "gov.cv/",
    "www.bcv.cv/",
    "www.ine.cv/",
    "www.tribunalconstitucional.cv/",
)

SEED_PDFS = [
    # filled dynamically; keep a couple known BO downloads as seeds
    "https://boe.incv.cv/Bulletins/Download/34017",
    "https://boe.incv.cv/Bulletins/Download/23930",
]


def _host_ok(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    if any(
        x in host
        for x in (
            "africanlii",
            "droit-afrique",
            "gazettes.africa",
            "law.africa",
        )
    ):
        return False
    if host.endswith((".pt", ".ao", ".st", ".ls", ".sz", ".bi", ".gq", ".gw")):
        return False
    if any(x in host for x in ("portugal", "angola", "saotome", "lesotho", "eswatini", "burundi")):
        return False
    if host.endswith(".gov.cv") or host in ("gov.cv", "www.gov.cv"):
        return True
    if host.endswith(".cv"):
        return any(host == s or host.endswith("." + s) for s in ALLOWED) or host in ALLOWED
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


def _is_bo_pdf(url: str) -> bool:
    path = unquote(urlsplit(url).path).lower()
    return "/bulletins/download/" in path or bool(
        re.search(r"(?i)(boletim.?oficial|bo[_/\-]|serie)", path)
    )


def _keep_pdf(url: str, title: str | None = None) -> bool:
    if not _host_ok(url):
        return False
    blob = unquote(urlsplit(url).path) + " " + url + " " + (title or "")
    if DROP_RE.search(blob):
        return False
    path = unquote(urlsplit(url).path).lower()
    if not path.endswith(".pdf") and "/bulletins/download/" not in path:
        return False
    if any(x in path for x in ("/css/", "favicon", "apple-touch", ".css", "webmanifest", "/js/")):
        return False
    if _is_bo_pdf(url):
        return True
    return bool(KEEP_RE.search(blob))


def _api_get(path: str, params: dict | None = None) -> dict | None:
    qs = ("?" + urlencode(params, doseq=True)) if params else ""
    url = f"{API}/{path.lstrip('/')}{qs}"
    try:
        r = http_get(url, ua=UA, timeout=(15, 60), retries=2, sleep=0.2, headers=API_HEADERS)
        if getattr(r, "status_code", 0) != 200:
            log.info("api status=%s %s", getattr(r, "status_code", None), url[:120])
            return None
        raw = (r.text or "").strip()
        if not raw.startswith("{") and not raw.startswith("["):
            return None
        return json.loads(raw)
    except Exception as exc:
        log.info("api %s %s", path, exc)
        return None


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
                    ["tesseract", str(img), "stdout", "-l", "por+fra+spa", "--psm", "6"],
                    check=False, capture_output=True, timeout=120,
                )
                if tproc.returncode == 0 and tproc.stdout:
                    chunks.append(tproc.stdout.decode("utf-8", "replace").strip())
            return "\n\n".join(c for c in chunks if c).strip()
    except Exception as exc:
        log.warning("ocr_pdf: %s", exc)
        return ""


def fetch_cv(url: str, wayback_ts: str | None = None) -> dict:
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
    log.info("OCR por %s bytes=%s", _ident_from_url(url)[:40], len(body))
    ocr = ocr_pdf(body)
    if len(ocr) >= 120:
        got.update(status="success", text=ocr, content=body, method="ocr_por")
        return got
    got["error"] = (got.get("error") or "") + ";ocr_short"
    return got


def _add(items, seen, ident, url, ts=None, priority=50, size_hint=None, title=None, kind="pdf", text=None, meta=None):
    url = _norm_url(url) if url else ""
    if kind == "pdf":
        if not url or not _keep_pdf(url, title=title):
            return
        key = url.lower().split("?")[0]
    else:
        # act text from official API
        if not text or len(text) < 120:
            return
        key = f"act:{ident}"
    key2 = key.replace("://www.", "://")
    if key in seen or key2 in seen:
        return
    if size_hint and size_hint > MAX_PDF_BYTES:
        return
    seen.add(key)
    seen.add(key2)
    ident = re.sub(r"\W+", "-", (ident or _ident_from_url(url, title)).strip("-")).lower()[:160]
    items.append((priority, ident, url, ts, size_hint, title, kind, text, meta or {}))


def _discover_acts(items, seen):
    """Primary: official BOE ActFilter JSON with embedded HTML law text."""
    for q in ACT_QUERIES:
        data = _api_get("Filter/ActFilter", {"query": q})
        if not data or not data.get("success"):
            continue
        n = 0
        for act in data.get("content") or []:
            aid = act.get("id")
            if not aid:
                continue
            html = act.get("content") or ""
            text = html_to_text(html)
            summary = (act.get("summary") or "").strip()
            legal = (act.get("legalNorm") or "").strip()
            if len(text) < 200:
                continue
            if not TEXT_KEEP_RE.search(text[:8000]) and not TEXT_KEEP_RE.search(summary + " " + legal):
                continue
            # Prefer substantive instruments
            pri = 18
            blob = (summary + " " + legal + " " + text[:2000]).lower()
            if re.search(r"constitui", blob):
                pri = 4
            elif re.search(r"c[oó]digo", blob):
                pri = 6
            elif re.search(r"\blei\b|decreto.?lei|decreto.?legislativo", blob):
                pri = 8
            elif re.search(r"regulamento|estatuto|portaria", blob):
                pri = 12
            title = summary or legal or f"Acto BOE {aid}"
            title = re.sub(r"\s+", " ", title).strip()[:240]
            source_url = f"https://boe.incv.cv/Bulletins/View/{aid}"
            ident = f"boe-act-{aid}-{_ident_from_url(source_url, title)[:80]}"
            _add(
                items, seen, ident, source_url, ts=None, priority=pri,
                title=title, kind="act", text=text,
                meta={
                    "act_id": aid,
                    "is_full_text": act.get("isFullText"),
                    "query": q,
                    "legal_norm": legal[:500] if legal else None,
                },
            )
            n += 1
        log.info("actfilter q=%r hits=%s kept~%s overmax=%s", q, len(data.get("content") or []), n, data.get("overmax"))


def _discover_bo_pdfs(items, seen):
    """Enumerate recent Boletim Oficial PDF downloads via Home API calendar."""
    months_back = env_int("BO_MONTHS", 18)
    today = date.today()
    # walk month starts
    y, m = today.year, today.month
    for _ in range(months_back):
        start = date(y, m, 1)
        if m == 12:
            end = date(y, 12, 31)
        else:
            end = date(y, m + 1, 1) - timedelta(days=1)
        days = _api_get("Home/DaysWithPublications", {"start": start.isoformat(), "end": end.isoformat()})
        content = (days or {}).get("content") or {}
        # Cap days per month to keep lean
        day_keys = sorted(content.keys(), reverse=True)[: env_int("BO_DAYS_PER_MONTH", 8)]
        for day_key in day_keys:
            day_s = day_key[:10]
            for serie in (1, 2):  # I Série priority, then II
                bf = _api_get("Home/BulletinFilter", {"serie": serie, "date": day_s})
                for b in (bf or {}).get("content") or []:
                    bid = b.get("id")
                    if not bid:
                        continue
                    number = b.get("number")
                    series = ((b.get("series") or {}).get("description")) or f"Série {serie}"
                    date_fmt = b.get("dateFormat") or day_s
                    title = f"Boletim Oficial n.º {number}, {series} de {date_fmt}"
                    if b.get("numberSup"):
                        title = (
                            f"Boletim Oficial n.º {number}, {b.get('numberSup')}.º Suplemento, "
                            f"{series} de {date_fmt}"
                        )
                    url = f"https://boe.incv.cv/Bulletins/Download/{bid}"
                    pri = 10 if serie == 1 else 16
                    _add(
                        items, seen, f"bo-{bid}-{number}-s{serie}", url,
                        ts=None, priority=pri, title=title, kind="pdf",
                        meta={"bulletin_id": bid, "serie": serie, "number": number},
                    )
        # previous month
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    log.info("bo pdf candidates so far=%s", sum(1 for it in items if it[6] == "pdf"))


def discover():
    items = []
    seen = set()

    for seed in SEED_PDFS:
        _add(items, seen, _ident_from_url(seed), seed, ts=None, priority=9, title="Boletim Oficial seed")

    _discover_acts(items, seen)
    _discover_bo_pdfs(items, seen)

    for home in HOMES:
        try:
            r = live_get(home, ua=UA, verify=False, timeout=(12, 40), retries=1)
            if getattr(r, "status_code", 0) != 200:
                log.info("home status=%s %s", getattr(r, "status_code", None), home)
                continue
            text = r.text or ""
            if re.search(r"(?i)(celtabet|gambling|casino|bet365)", text[:2000]):
                log.info("home compromised/skip %s", home)
                continue
            n = 0
            for href in re.findall(r"""href=["']([^"']+)["']""", text, re.I):
                full = urljoin(home, html_lib.unescape(href))
                if ".pdf" in full.lower() or "/Bulletins/Download/" in full:
                    pri = 20
                    low = unquote(full).lower()
                    if re.search(r"(?i)(constitu)", low):
                        pri = 5
                    elif re.search(r"(?i)(lei|decreto|codigo|regulamento)", low):
                        pri = 12
                    elif _is_bo_pdf(full):
                        pri = 14
                    _add(items, seen, _ident_from_url(full), full, ts=None, priority=pri)
                    n += 1
            for href in re.findall(r"(https?://[^\s\"'<>]+\.pdf)", text, re.I):
                _add(items, seen, _ident_from_url(href), href, ts=None, priority=22)
                n += 1
            sub = []
            for href in re.findall(r"""href=["']([^"']+)["']""", text, re.I):
                full = urljoin(home, html_lib.unescape(href))
                if not _host_ok(full):
                    continue
                low = unquote(full).lower()
                if any(
                    k in low
                    for k in (
                        "lei", "leis", "decreto", "constitu", "boletim", "legisl",
                        "documento", "download", "upload", "files", "regulamento",
                        "norma", "ficheiros", "codigo",
                    )
                ):
                    if full not in sub and not low.endswith(".pdf"):
                        sub.append(full)
            for sub_url in sub[:6]:
                try:
                    r2 = live_get(sub_url, ua=UA, verify=False, timeout=(10, 30), retries=1)
                    if getattr(r2, "status_code", 0) != 200:
                        continue
                    t2 = r2.text or ""
                    for href in re.findall(r"""href=["']([^"']+)["']""", t2, re.I):
                        full = urljoin(sub_url, html_lib.unescape(href))
                        if ".pdf" in full.lower() or "/Bulletins/Download/" in full:
                            pri = 18
                            low = unquote(full).lower()
                            if re.search(r"(?i)(constitu)", low):
                                pri = 5
                            elif re.search(r"(?i)(lei|decreto|codigo)", low):
                                pri = 12
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
                limit=env_int("CDX_LIMIT", 120),
                match_type="prefix",
                extra_filters=["statuscode:200", "mimetype:application/pdf"],
            ) or []
        except Exception as exc:
            log.info("cdx %s %s", prefix, exc)
            hits = []
        if len(hits) < 3:
            try:
                hits2 = cdx_urls(
                    prefix,
                    limit=env_int("CDX_LIMIT", 120),
                    match_type="prefix",
                    extra_filters=["statuscode:200"],
                ) or []
                for h in hits2:
                    orig = (h.get("original") or "").lower()
                    if ".pdf" in orig or "/bulletins/download/" in orig:
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
            if not _keep_pdf(orig):
                continue
            pri = 30
            low = unquote(orig).lower()
            if re.search(r"(?i)(constitu)", low):
                pri = 5
            elif _is_bo_pdf(orig):
                pri = 15
            elif re.search(r"(?i)(lei|codigo|regulamento)", low):
                pri = 14
            elif re.search(r"(?i)(decreto|diploma|resolu|portaria|despacho)", low):
                pri = 22
            _add(items, seen, _ident_from_url(orig), orig, ts=ts, priority=pri, size_hint=length or None)

    items.sort(key=lambda x: (x[0], x[1]))
    out = [
        (ident, url, ts, size, title, kind, text, meta)
        for _, ident, url, ts, size, title, kind, text, meta in items
    ]
    log.info("catalog %s (acts=%s pdfs=%s)", len(out), sum(1 for x in out if x[5] == "act"), sum(1 for x in out if x[5] == "pdf"))
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
    for ident, url, ts, size_hint, title, kind, preset_text, meta in discover():
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
        if url and not _host_ok(url):
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "host_not_cv"})
            continue

        if kind == "act" and preset_text:
            text = preset_text
            method = "boe_actfilter_html"
            got = {"status": "success", "method": method, "text": text}
        else:
            got = fetch_cv(url, wayback_ts=ts)
            text = got.get("text") or ""
            method = got.get("method")

        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error"), "wayback_ts": ts})
            continue
        if len(text) > 2_500_000:
            log.info("skip huge text chars=%s %s", len(text), ident[:50])
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "text_too_large", "chars": len(text)})
            continue
        if not TEXT_KEEP_RE.search(text[:8000]) and not _is_bo_pdf(url or ""):
            if not re.search(r"(?i)(lei|decreto|constitu|codigo|regulamento|diploma|boletim|acord)", ident):
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
            title=use_title or ident, text=text, source_url=url or f"https://boe.incv.cv/",
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_cv.py",
            article_re=ART,
            extra_meta={
                "fetch_method": method,
                "wayback_ts": ts,
                "size_hint": size_hint,
                **(meta or {}),
            },
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s ts=%s", ident[:60], method, len(text), ts)
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY,
        source="Cabo Verde Boletim Oficial / Laws (boe.incv.cv / governo.cv / parlamento.cv / justica.gov.cv / mf.gov.cv)",
        source_urls=[
            "https://boe.incv.cv/",
            "https://incv.cv/",
            "https://www.governo.cv/",
            "https://www.parlamento.cv/",
            "https://justica.gov.cv/",
            "https://www.mf.gov.cv/",
            "https://www.gov.cv/",
            "https://www.bcv.cv/",
            "https://www.tribunalconstitucional.cv/",
        ],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (BOE ActFilter HTML + BO PDF downloads + live/CDX *.cv / *.gov.cv)",
        notes=(
            "Official *.cv / *.gov.cv lei/decreto/constituição / Boletim Oficial only "
            "(Cabo Verde). Primary: boe.incv.cv /api/v1 ActFilter + Bulletin Download. "
            "OCR por+fra+spa for scans. Not AfricanLII. No WAF bypass. Not legal advice. "
            "cv=Cabo Verde (not Portugal/pt, not Angola/ao, not São Tomé/st)."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s total_instruments=%s", ok, skip, fail, len(done))


if __name__ == "__main__":
    main()
