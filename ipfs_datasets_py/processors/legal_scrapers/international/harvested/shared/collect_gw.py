#!/usr/bin/env python3
"""Guinea-Bissau (gw): official law / Boletim Oficial PDFs from *.gw / *.gov.gw.

Official only (Portuguese primary) — NOT Guinea (gn) / Equatorial Guinea (gq) /
Cabo Verde (cv) / São Tomé (st):
  - https://anp.gw/  (Assembleia Nacional Popular)
  - https://www.parlamento.gw/ / parlamento.gw
  - https://www.presidencia.gw/ / presidencia.gw
  - https://www.mef.gw/ / mef.gw (Ministério da Economia e Finanças)
  - https://gov.gw/ / www.gov.gw (historical portal; CDX)
  - https://ine.gw/ / www.ine.gw
  - governo.gw (often Plesk-login dead; CDX only if usable)
  - Boletim Oficial / INCM / Justiça hosts under *.gw / *.gov.gw when present
  - Wayback/CDX of the same official *.gw / *.gov.gw URLs

Filter: prefer lei/decreto/constituição/código/Boletim Oficial; skip PDFs >12MB.
Not AfricanLII / Droit-Afrique. No WAF bypass. Not legal advice.
NOTE: country code gw = Guinea-Bissau (not gn Guinea, not gq Equatorial Guinea).
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
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

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

CC, COUNTRY, LANG = "gw", "Guinea-Bissau", "pt"
SOURCE_TYPE = "guineabissau_official_boletim_oficial_laws"
LICENSE = (
    "República da Guiné-Bissau — Assembleia Nacional Popular (anp.gw / parlamento.gw) / "
    "Presidência (presidencia.gw) / MEF (mef.gw) / gov.gw / INE and other *.gw / *.gov.gw "
    "gazette hosts. Authentic Boletim Oficial / official text prevails. Not legal advice. "
    "Not Guinea (gn) / Equatorial Guinea (gq) / Cabo Verde (cv) / São Tomé (st)."
)
UA = (
    "legal-corpora-collector/1.0 (research; source=https://anp.gw/; "
    "GuineaBissau=gw not gn/gq/cv/st)"
)
ART = re.compile(
    r"(?im)^\s*((?:Artigo|Art\.?|Secção|Secao|Capítulo|Capitulo|Cap\.?|"
    r"Título|Titulo|Parte|Disposição|Disposicao)\s*[IVXLC0-9º°a-zA-Z]*)\b"
)
log = logging.getLogger("gw")

MAX_PDF_BYTES = 12 * 1024 * 1024

ALLOWED = (
    "anp.gw",
    "www.anp.gw",
    "parlamento.gw",
    "www.parlamento.gw",
    "assembleia.gw",
    "www.assembleia.gw",
    "assembleianacional.gw",
    "www.assembleianacional.gw",
    "presidencia.gw",
    "www.presidencia.gw",
    "governo.gw",
    "www.governo.gw",
    "gov.gw",
    "www.gov.gw",
    "mef.gw",
    "www.mef.gw",
    "ine.gw",
    "www.ine.gw",
    "justica.gw",
    "www.justica.gw",
    "justica.gov.gw",
    "www.justica.gov.gw",
    "mj.gw",
    "www.mj.gw",
    "mj.gov.gw",
    "www.mj.gov.gw",
    "incm.gw",
    "www.incm.gw",
    "boletimoficial.gw",
    "www.boletimoficial.gw",
    "boletim.gw",
    "www.boletim.gw",
    "bo.gw",
    "www.bo.gw",
    "imprensa.gw",
    "www.imprensa.gw",
    "imprensanacional.gw",
    "www.imprensanacional.gw",
    "diario.gw",
    "www.diario.gw",
    "stj.gw",
    "www.stj.gw",
    "tribunal.gw",
    "www.tribunal.gw",
    "tribunalconstitucional.gw",
    "www.tribunalconstitucional.gw",
    "bcg.gw",
    "www.bcg.gw",
    "mnec.gw",
    "www.mnec.gw",
    "minfin.gw",
    "www.minfin.gw",
    "financas.gw",
    "www.financas.gw",
    "legis.gw",
    "www.legis.gw",
    "primatura.gw",
    "www.primatura.gw",
    "sgg.gw",
    "www.sgg.gw",
)

KEEP_RE = re.compile(
    r"(lei|leis|decreto|diploma|resolu[cç][aã]o|proclama|"
    r"constitui[cç][aã]o|regulamento|portaria|despacho|"
    r"boletim|diario|di[aá]rio|republica|rep[uú]blica|gazette|jornal|"
    r"legislacao|legisla[cç][aã]o|normativo|estatuto|codigo|c[oó]digo|"
    r"amendment|altera[cç][aã]o|lei[_/\-]|decreto[_/\-]|"
    r"regimento|oge|orcamento|or[cç]amento|cidadania|partidos|"
    r"eleitoral|autarqu|recenseamento|observacao|"
    r"wp-content/uploads|/_files/|/uploads/|/files/|/documents?/|/ficheiros?/|"
    r"viewdocument|/file\b|at_download|"
    r"guine.?bissau|guin[eé].?bissau)",
    re.I,
)
DROP_RE = re.compile(
    r"(africanlii|droit-afrique|gazettes\.africa|law\.africa|"
    r"discurso|allocution|communique|comunicado.?de.?imprensa|nota.?de.?prensa|"
    r"photo|banner|logo|cv[-_]|biograf|organigrama|organigrama|presentacion|"
    r"newsletter|facebook|twitter|linkedin|album|actualites|licitacao|"
    r"favicon|apple-touch|webmanifest|/css/|\.css\b|"
    r"boletim.?estatistico|estatisticas.?da.?divida|nota.?e.?boletim.?de.?conjuntura|"
    r"relatorio.?anti.?corrupcao|medidas.?implemetadas|medidas.?de.?melhoria|"
    r"ex-parlamentares|vii-legislatura|viii-legislatura|"
    r"guinea(?!.?bissau)|conakry|\.gn/|sgg\.gov\.gn|"
    r"guinea.?ecuatorial|\.gq/|malabo|boe\.gob\.gq|"
    r"cabo.?verde|\.cv/|boe\.incv\.cv|"
    r"sao.?tome|\.st/|governo\.st|"
    r"angola|\.ao/|imprensanacional\.gov\.ao|"
    r"bceao\.int)",
    re.I,
)
TEXT_KEEP_RE = re.compile(
    r"\b(lei|decreto|diploma|constitui[cç][aã]o|boletim\s+oficial|"
    r"c[oó]digo|rep[uú]blica\s+da\s+guin[eé].?bissau|"
    r"assembleia\s+nacional|presidente\s+da\s+rep[uú]blica|promulga|"
    r"artigo|guin[eé].?bissau|resolu[cç][aã]o|regulamento|regimento|"
    r"estatuto|orcamento|or[cç]amento)\b",
    re.I,
)

SEED_PDFS = [
    "https://anp.gw/wp-content/uploads/2022/08/estatuto-dos-deputados.pdf",
    "https://anp.gw/wp-content/uploads/2022/08/REGIMENTO-Lei-No-1-2010.pdf",
    "https://www.presidencia.gw/_files/ugd/f25026_df0e7a77dd0c49dbb24263438d5a1bf1.pdf",
    "https://www.presidencia.gw/_files/ugd/2bc2a0_9cd32c611a174aeca66bd9e91cfb1ccf.pdf",
    "https://www.presidencia.gw/_files/ugd/b4d724_413ea9591ef44b5d9c40d59cf6ca9bbb.pdf",
    "https://www.presidencia.gw/_files/ugd/b4d724_0703efe348604fb38d40b8a37f3ae89f.pdf",
    "https://www.presidencia.gw/_files/ugd/b4d724_460c9818469c42ca88382c6ff7192921.pdf",
    "https://www.presidencia.gw/_files/ugd/b4d724_b6a56154ecae490781bc364e87db0686.pdf",
    "https://www.presidencia.gw/_files/ugd/2bc2a0_606159868df2475193af108b50791cc8.pdf",
]

HOMES = [
    "https://anp.gw/",
    "https://www.anp.gw/",
    "https://anp.gw/index.php/constituicao/",
    "https://anp.gw/index.php/legislacao/",
    "https://anp.gw/index.php/leis-autarquicas/",
    "https://anp.gw/index.php/lei-da-cidadania/",
    "https://anp.gw/index.php/lei-do-recenseamento-eleitoral/",
    "https://anp.gw/index.php/lei-da-observacao-internacional-eleitoral/",
    "https://anp.gw/index.php/lei-quadro-dos-partidos-politicos/",
    "https://anp.gw/index.php/resolucoes-e-comunicados/",
    "https://www.parlamento.gw/",
    "https://parlamento.gw/",
    "https://www.parlamento.gw/leis",
    "https://www.parlamento.gw/leis/constituicao",
    "https://www.parlamento.gw/leis/legislacao",
    "https://www.parlamento.gw/leis/estatutos-e-regimentos",
    "https://www.parlamento.gw/leis/leis-federais",
    "https://www.parlamento.gw/leis/tratados-e-acordos-internacionais",
    "https://www.parlamento.gw/institucional/resolucoes-e-comunicados",
    "https://www.presidencia.gw/",
    "https://presidencia.gw/",
    "https://www.mef.gw/",
    "https://mef.gw/",
    "https://ine.gw/",
    "https://www.ine.gw/",
]

CDX_PREFIXES = (
    "anp.gw/",
    "www.anp.gw/",
    "parlamento.gw/",
    "www.parlamento.gw/",
    "presidencia.gw/",
    "www.presidencia.gw/",
    "mef.gw/",
    "www.mef.gw/",
    "gov.gw/",
    "www.gov.gw/",
    "governo.gw/",
    "www.governo.gw/",
    "ine.gw/",
    "www.ine.gw/",
    "assembleia.gw/",
    "www.assembleia.gw/",
    "justica.gw/",
    "www.justica.gw/",
    "incm.gw/",
    "www.incm.gw/",
    "boletimoficial.gw/",
    "www.boletimoficial.gw/",
    "boletim.gw/",
    "imprensa.gw/",
    "imprensanacional.gw/",
    "stj.gw/",
    "tribunalconstitucional.gw/",
    "bcg.gw/",
    "www.bcg.gw/",
)


def _host_ok(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    if any(
        x in host
        for x in (
            "africanlii",
            "droit-afrique",
            "gazettes.africa",
            "law.africa",
            "bceao.int",
            "parastorage.com",
            "facebook.com",
            "stat-guinebissau.com",
        )
    ):
        return False
    # Never harvest Guinea (gn), Equatorial Guinea (gq), Cabo Verde (cv), São Tomé (st), Angola
    if host.endswith((".gn", ".gq", ".cv", ".st", ".ao", ".cg", ".cd", ".ga")):
        return False
    if any(
        x in host
        for x in (
            "gob.gq",
            "guineaecuatorial",
            "sgg.gov.gn",
            "incv.cv",
            "governo.st",
            "imprensanacional.gov.ao",
        )
    ):
        return False
    if host.endswith(".gov.gw") or host in ("gov.gw", "www.gov.gw"):
        return True
    if host.endswith(".gw"):
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
    if stem in ("file", "at_download", "viewdocument") or stem.isdigit():
        # use last meaningful path segments
        segs = [s for s in path.strip("/").split("/") if s and s not in ("file", "at_download", "viewdocument")]
        stem = "-".join(segs[-3:]) if segs else stem
    return re.sub(r"\W+", "-", stem).strip("-").lower()[:160] or re.sub(r"\W+", "-", url)[-80:]


def _is_boletim(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    path = unquote(urlsplit(url).path).lower()
    if any(x in host for x in ("boletim", "incm", "imprensa", "diario")):
        return path.endswith(".pdf") or "/files/" in path or "boletim" in path or "diario" in path
    return bool(
        re.search(
            r"(?i)(boletim.?oficial|di[aá]rio.?da.?rep|constituicao|constitui[cç][aã]o)",
            path,
        )
    )


def _looks_pdf(url: str) -> bool:
    low = url.lower().split("?")[0]
    path = unquote(urlsplit(url).path).lower()
    if path.endswith(".pdf") or low.endswith(".pdf"):
        return True
    if "/at_download/" in path or path.endswith("/file") or "/viewdocument/" in path:
        return True
    if "/_files/ugd/" in path:
        return True
    if "/wp-content/uploads/" in path and path.endswith(".pdf"):
        return True
    return False


def _keep(url: str, title: str | None = None) -> bool:
    if not _host_ok(url):
        return False
    blob = unquote(urlsplit(url).path) + " " + url + " " + (title or "")
    if DROP_RE.search(blob):
        return False
    path = unquote(urlsplit(url).path).lower()
    if any(x in path for x in ("/css/", "favicon", "apple-touch", ".css", "webmanifest", "/js/")):
        return False
    if not _looks_pdf(url):
        return False
    if _is_boletim(url):
        return True
    # MEF: keep law/budget/code; drop pure debt-stat bulletins (already in DROP)
    host = (urlsplit(url).hostname or "").lower()
    if "mef.gw" in host:
        return bool(
            re.search(
                r"(?i)(lei|decreto|codigo|c[oó]digo|orcamento|or[cç]amento|oge|"
                r"regulamento|diploma|legisl|constitu|portaria|despacho|norma)",
                blob,
            )
        )
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
                    ["tesseract", str(img), "stdout", "-l", "por+fra", "--psm", "6"],
                    check=False, capture_output=True, timeout=120,
                )
                if tproc.returncode == 0 and tproc.stdout:
                    chunks.append(tproc.stdout.decode("utf-8", "replace").strip())
            return "\n\n".join(c for c in chunks if c).strip()
    except Exception as exc:
        log.warning("ocr_pdf: %s", exc)
        return ""


def fetch_gw(url: str, wayback_ts: str | None = None) -> dict:
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
        pri = 5 if re.search(r"(?i)(constitu)", seed) else 8
        if re.search(r"(?i)(regimento|estatuto|lei)", seed):
            pri = 6
        _add(items, seen, _ident_from_url(seed), seed, ts=None, priority=pri)

    for home in HOMES:
        try:
            r = live_get(home, ua=UA, verify=False, timeout=(12, 40), retries=1)
            if getattr(r, "status_code", 0) != 200:
                log.info("home status=%s %s", getattr(r, "status_code", None), home)
                continue
            text = r.text or ""
            if re.search(r"(?i)(celtabet|gambling|casino|bet365|plesk|login_up\.php)", text[:2500]):
                log.info("home compromised/skip %s", home)
                continue
            n = 0
            for href in re.findall(r"""href=["']([^"']+)["']""", text, re.I):
                full = urljoin(home, html_lib.unescape(href))
                if _looks_pdf(full) or "/files/" in full.lower() or "/uploads/" in full.lower() or "/_files/" in full.lower():
                    pri = 15
                    low = unquote(full).lower()
                    if re.search(r"(?i)(constitu)", low):
                        pri = 5
                    elif re.search(r"(?i)(lei|decreto|codigo|regulamento|regimento|estatuto)", low):
                        pri = 10
                    elif _is_boletim(full):
                        pri = 12
                    _add(items, seen, _ident_from_url(full), full, ts=None, priority=pri)
                    n += 1
            for href in re.findall(r"(https?://[^\s\"'<>]+\.pdf)", text, re.I):
                _add(items, seen, _ident_from_url(href), href, ts=None, priority=18)
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
                        "lei", "leis", "decreto", "constitu", "boletim", "diario",
                        "texto", "documento", "download", "upload", "files",
                        "legisl", "regulamento", "norma", "ficheiros", "estatuto",
                        "regimento", "cidadania", "eleitoral", "autarqu", "partido",
                    )
                ):
                    if full not in sub and not _looks_pdf(full):
                        sub.append(full)
            for sub_url in sub[:10]:
                try:
                    r2 = live_get(sub_url, ua=UA, verify=False, timeout=(10, 30), retries=1)
                    if getattr(r2, "status_code", 0) != 200:
                        continue
                    t2 = r2.text or ""
                    for href in re.findall(r"""href=["']([^"']+)["']""", t2, re.I):
                        full = urljoin(sub_url, html_lib.unescape(href))
                        if _looks_pdf(full) or "/files/" in full.lower() or "/uploads/" in full.lower() or "/_files/" in full.lower():
                            pri = 16
                            low = unquote(full).lower()
                            if re.search(r"(?i)(constitu)", low):
                                pri = 5
                            elif re.search(r"(?i)(lei|decreto|codigo|regimento|estatuto)", low):
                                pri = 10
                            _add(items, seen, _ident_from_url(full), full, ts=None, priority=pri)
                            n += 1
                    for href in re.findall(r"(https?://[^\s\"'<>]+\.pdf)", t2, re.I):
                        _add(items, seen, _ident_from_url(href), href, ts=None, priority=16)
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
                limit=env_int("CDX_LIMIT", 220),
                match_type="prefix",
                extra_filters=["statuscode:200", "mimetype:application/pdf"],
            ) or []
        except Exception as exc:
            log.info("cdx %s %s", prefix, exc)
            hits = []
        if len(hits) < 8:
            try:
                hits2 = cdx_urls(
                    prefix,
                    limit=env_int("CDX_LIMIT", 220),
                    match_type="prefix",
                    extra_filters=["statuscode:200"],
                ) or []
                for h in hits2:
                    orig = (h.get("original") or "").lower()
                    if ".pdf" in orig or "/file" in orig or "viewdocument" in orig or "at_download" in orig:
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
            if re.search(r"(?i)(constitu)", low):
                pri = 5
            elif _is_boletim(orig):
                pri = 14
            elif re.search(r"(?i)(lei|codigo|regulamento|regimento|estatuto)", low):
                pri = 12
            elif re.search(r"(?i)(decreto|diploma|resolu|portaria|despacho|oge|orcamento)", low):
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
        if not _host_ok(url):
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "host_not_gw"})
            continue
        got = fetch_gw(url, wayback_ts=ts)
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
        if not TEXT_KEEP_RE.search(text[:8000]) and not _is_boletim(url):
            if not re.search(r"(?i)(lei|decreto|constitu|codigo|regulamento|diploma|regimento|estatuto|oge|orcamento)", ident):
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
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_gw.py",
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
        source="Guinea-Bissau (anp.gw / parlamento.gw / Presidência / MEF / gov.gw)",
        source_urls=[
            "https://anp.gw/",
            "https://www.parlamento.gw/",
            "https://www.presidencia.gw/",
            "https://www.mef.gw/",
            "https://gov.gw/",
            "https://ine.gw/",
        ],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (live crawl *.gw / *.gov.gw + CDX PDF / Boletim)",
        notes=(
            "Official *.gw / *.gov.gw lei/decreto/constituição PDFs only "
            "(Guinea-Bissau). OCR por+fra for scans. "
            "Not AfricanLII. No WAF bypass. Not legal advice. "
            "gw=Guinea-Bissau (not Guinea/gn, not Equatorial Guinea/gq, not Cabo Verde/cv, not São Tomé/st)."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s total_instruments=%s", ok, skip, fail, len(done))


if __name__ == "__main__":
    main()
