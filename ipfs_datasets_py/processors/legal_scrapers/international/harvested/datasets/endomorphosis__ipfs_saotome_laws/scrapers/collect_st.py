#!/usr/bin/env python3
"""São Tomé and Príncipe (st): official law / Diário da República PDFs from *.st / *.gov.st.

Official only (NOT Equatorial Guinea gq / Gabon ga / Angola ao):
  - https://www.governo.st/ / governo.st (Portal do Governo)
  - https://www.assembleia.st/ / assembleia.st / parlamento.st (Assembleia Nacional)
  - https://www.presidencia.st/ / presidencia.st
  - https://justica.gov.st/ / www.justica.gov.st
  - https://financas.gov.st/ / www.financas.gov.st / minfinancas.gov.st
  - https://www.gov.st/ / gov.st
  - https://www.bcstp.st/ (Banco Central)
  - https://www.ine.st/ / ine.st
  - https://www.tribunalconstitucional.st/
  - Diário da República / jornal oficial hosts under *.st / *.gov.st
  - Wayback/CDX of the same official *.st / *.gov.st URLs

Filter: prefer lei/decreto/constituição/código/Diário; skip PDFs >12MB.
Not AfricanLII / Droit-Afrique. No WAF bypass. Not legal advice.
NOTE: country code st = São Tomé and Príncipe (not gq Equatorial Guinea).
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

CC, COUNTRY, LANG = "st", "Sao Tome and Principe", "pt"
SOURCE_TYPE = "saotome_official_diario_republica_laws"
LICENSE = (
    "República Democrática de São Tomé e Príncipe — Portal do Governo (governo.st) / "
    "Assembleia Nacional (assembleia.st / parlamento.st) / Presidência (presidencia.st) / "
    "Justiça (justica.gov.st) / Finanças (financas.gov.st) / gov.st / BCSTP / INE / "
    "Tribunal Constitucional and other *.st / *.gov.st gazette hosts. Authentic Diário da "
    "República / official text prevails. Not legal advice. Not Equatorial Guinea (gq) / "
    "Gabon (ga) / Angola (ao)."
)
UA = (
    "legal-corpora-collector/1.0 (research; source=https://www.governo.st/; "
    "SaoTomePrincipe=st not gq/ga/ao)"
)
ART = re.compile(
    r"(?im)^\s*((?:Artigo|Art\.?|Secção|Secao|Capítulo|Capitulo|Cap\.?|"
    r"Título|Titulo|Parte|Disposição|Disposicao)\s*[IVXLC0-9º°a-zA-Z]*)\b"
)
log = logging.getLogger("st")

MAX_PDF_BYTES = 12 * 1024 * 1024

ALLOWED = (
    "governo.st",
    "www.governo.st",
    "assembleia.st",
    "www.assembleia.st",
    "parlamento.st",
    "www.parlamento.st",
    "presidencia.st",
    "www.presidencia.st",
    "gov.st",
    "www.gov.st",
    "justica.gov.st",
    "www.justica.gov.st",
    "financas.gov.st",
    "www.financas.gov.st",
    "minfinancas.gov.st",
    "www.minfinancas.gov.st",
    "mnec.gov.st",
    "www.mnec.gov.st",
    "stp.gov.st",
    "www.stp.gov.st",
    "bcstp.st",
    "www.bcstp.st",
    "ine.st",
    "www.ine.st",
    "tribunalconstitucional.st",
    "www.tribunalconstitucional.st",
    "tribunal.st",
    "www.tribunal.st",
    "jornal.st",
    "www.jornal.st",
    "diario.st",
    "www.diario.st",
    "imprensa.st",
    "www.imprensa.st",
    "imprensanacional.st",
    "www.imprensanacional.st",
    "saudestp.gov.st",
    "www.saudestp.gov.st",
    "educacao.gov.st",
    "www.educacao.gov.st",
    "trabalho.gov.st",
    "www.trabalho.gov.st",
    "agricultura.gov.st",
    "www.agricultura.gov.st",
    "defesa.gov.st",
    "www.defesa.gov.st",
    "interior.gov.st",
    "www.interior.gov.st",
    "planificacao.gov.st",
    "www.planificacao.gov.st",
    "mirn.gov.st",
    "www.mirn.gov.st",
    "afap.st",
    "www.afap.st",
    "anp.st",
    "www.anp.st",
    "arsa.st",
    "www.arsa.st",
    "coursupreme.st",
    "www.coursupreme.st",
    "supremo.st",
    "www.supremo.st",
)

KEEP_RE = re.compile(
    r"(lei|leis|decreto|diploma|resolu[cç][aã]o|proclama|"
    r"constitui[cç][aã]o|regulamento|portaria|despacho|"
    r"diario|di[aá]rio|republica|rep[uú]blica|gazette|jornal|"
    r"legislacao|legisla[cç][aã]o|normativo|estatuto|codigo|c[oó]digo|"
    r"amendment|altera[cç][aã]o|lei[_/\-]|decreto[_/\-]|"
    r"wp-content/uploads|/uploads/|/files/|/documents?/|/ficheiros?/|"
    r"phocadownload|/Legislacoes?/|/NAP/|oge.*lei|lei.*oge|"
    r"download=\d+:(?:decreto|lei)|acord[aã]o|"
    r"sao.?tome|s[aã]o.?tom[eé]|principe|pr[ií]ncipe)",
    re.I,
)
DROP_RE = re.compile(
    r"(africanlii|droit-afrique|gazettes\.africa|law\.africa|"
    r"discurso|allocution|communique|comunicado|nota.?de.?prensa|photo|banner|logo|"
    r"cv[-_]|biograf|organigrama|presentacion|newsletter|curricul|"
    r"facebook|twitter|linkedin|album|actualites|licitacao|"
    r"favicon|apple-touch|webmanifest|/css/|\.css\b|"
    r"boletim.?estat|boletim.?de.?conjuntura|informa[cç][oõ]es.?estat|mics|inqu[eé]rito|atlas.?demogr|recenseamento.?empresarial|ficha.?de.?inscri|"
    r"hasta.?public|anuncio.?mapdr|ajudicacao|notas.?de.?rececao|"
    r"resultado.?do.?leil|leil[aã]o.?de.?bt|"
    r"gabon|\.ga/|brazzaville|\.cg/|kinshasa|\.cd/|"
    r"guinea.?ecuatorial|\.gq/|malabo|boe\.gob\.gq|"
    r"angola|\.ao/|imprensanacional\.gov\.ao)",
    re.I,
)
TEXT_KEEP_RE = re.compile(
    r"\b(lei|decreto|diploma|constitui[cç][aã]o|di[aá]rio\s+da\s+rep[uú]blica|"
    r"c[oó]digo|rep[uú]blica\s+democr[aá]tica\s+de\s+s[aã]o\s+tom[eé]|"
    r"assembleia\s+nacional|presidente\s+da\s+rep[uú]blica|promulga|"
    r"artigo|s[aã]o\s+tom[eé]|pr[ií]ncipe|resolu[cç][aã]o|regulamento)\b",
    re.I,
)

# High-value known / likely official law PDF paths (live + CDX will expand)
SEED_PDFS = [
    "https://www.governo.st/wp-content/uploads/constituicao.pdf",
    "https://governo.st/wp-content/uploads/constituicao.pdf",
    "https://www.assembleia.st/wp-content/uploads/constituicao.pdf",
    "https://assembleia.st/wp-content/uploads/Constituicao.pdf",
    "https://www.presidencia.st/wp-content/uploads/constituicao.pdf",
    "https://justica.gov.st/wp-content/uploads/constituicao.pdf",
    "https://www.justica.gov.st/wp-content/uploads/constituicao.pdf",
    "http://www.tribunalconstitucional.st/download/Constituicao.pdf",
    "https://www.ine.st/phocadownload/userupload/Documentos/Legislacao/2018/Diario%20Republica%202.pdf",
    "https://www.ine.st/phocadownload/userupload/Documentos/Legislacao/2018/DL39-2009%20-%20C%C3%B3digo%20Aduaneiro.pdf",
    "https://financas.gov.st/phocadownload/COSSIL/A-2022/Diversos/Lei_8_2009.pdf",
    "https://financas.gov.st/phocadownload/Orcamento/oge/A-2015/Aprovado/1%20Lei%20N.%201-2015%20-%20OGE-%20DR%20N.%2038.pdf",
    "http://www.bcstp.st/Legislacoes/Lei_Cambial.pdf",
    "http://www.bcstp.st/Legislacoes/Lei_Organica_BC.pdf",
    "http://www.bcstp.st/NAP/NAP_24_Regulamento_Casas_Cambio.pdf",
    "http://www.bcstp.st/upload/NAP/Dr_Lei_152017.pdf",
    "http://www.bcstp.st/upload/NAP/Lei.06.2015.pdf",
]

HOMES = [
    "https://www.governo.st/",
    "https://governo.st/",
    "https://www.governo.st/documentos/",
    "https://www.governo.st/legislacao/",
    "https://www.governo.st/leis/",
    "https://www.assembleia.st/",
    "https://assembleia.st/",
    "https://www.assembleia.st/leis/",
    "https://www.assembleia.st/legislacao/",
    "https://www.assembleia.st/documentos/",
    "https://www.parlamento.st/",
    "https://parlamento.st/",
    "https://www.presidencia.st/",
    "https://presidencia.st/",
    "https://www.presidencia.st/documentos/",
    "https://justica.gov.st/",
    "https://www.justica.gov.st/",
    "https://justica.gov.st/legislacao/",
    "https://financas.gov.st/",
    "https://www.financas.gov.st/",
    "https://financas.gov.st/legislacao/",
    "https://www.gov.st/",
    "https://gov.st/",
    "https://www.bcstp.st/",
    "https://www.ine.st/",
    "https://www.tribunalconstitucional.st/",
    "https://www.imprensanacional.st/",
    "https://www.jornal.st/",
]

CDX_PREFIXES = (
    "governo.st/",
    "www.governo.st/",
    "assembleia.st/",
    "www.assembleia.st/",
    "parlamento.st/",
    "www.parlamento.st/",
    "presidencia.st/",
    "www.presidencia.st/",
    "presidencia.st/index.php/",
    "www.presidencia.st/index.php/",
    "justica.gov.st/",
    "www.justica.gov.st/",
    "justica.gov.st/resources/",
    "financas.gov.st/",
    "www.financas.gov.st/",
    "financas.gov.st/phocadownload/",
    "www.financas.gov.st/phocadownload/",
    "gov.st/",
    "www.gov.st/",
    "bcstp.st/",
    "www.bcstp.st/",
    "bcstp.st/Upload/",
    "www.bcstp.st/Upload/",
    "bcstp.st/upload/",
    "www.bcstp.st/upload/",
    "bcstp.st/Legislacoes/",
    "www.bcstp.st/Legislacoes/",
    "ine.st/",
    "www.ine.st/",
    "ine.st/phocadownload/",
    "www.ine.st/phocadownload/",
    "ine.st/Documentacao/",
    "www.ine.st/Documentacao/",
    "tribunalconstitucional.st/",
    "www.tribunalconstitucional.st/",
    "tribunalconstitucional.st/wp-content/uploads/",
    "tribunalconstitucional.st/download/",
    "jornal.st/",
    "www.jornal.st/",
    "imprensanacional.st/",
    "www.imprensanacional.st/",
    "diario.st/",
    "www.diario.st/",
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
        )
    ):
        return False
    # Never harvest Equatorial Guinea (gq), Gabon (ga), Angola (ao), Congo
    if host.endswith((".gq", ".ga", ".ao", ".cg", ".cd", ".gn", ".gw")):
        return False
    if any(
        x in host
        for x in (
            "gob.gq",
            "guineaecuatorial",
            "gabon",
            "brazzaville",
            "kinshasa",
            "angola",
        )
    ):
        return False
    if host.endswith(".gov.st") or host in ("gov.st", "www.gov.st"):
        return True
    if host.endswith(".st"):
        # Allow listed official *.st hosts only (avoid random commercial .st)
        return any(host == s or host.endswith("." + s) for s in ALLOWED) or host in ALLOWED
    return any(host == s or host.endswith("." + s) for s in ALLOWED)


def _norm_url(url: str) -> str:
    url = html_lib.unescape((url or "").split("#")[0].strip())
    if not url:
        return ""
    url = url.replace(":80/", "/").replace(":80?", "?")
    # Preserve original scheme for Wayback keying when download= present;
    # still normalize host case / path encoding.
    try:
        p = urlsplit(url)
        host = (p.hostname or "").lower()
        parts = []
        for seg in p.path.split("/"):
            if not seg:
                parts.append(seg)
                continue
            parts.append(seg if "%" in seg else quote(seg, safe="._-()[]',"))
        # Keep query when it carries download= (Presidência Joomla PDF links)
        q = p.query if (p.query and "download=" in p.query.lower()) else ""
        scheme = p.scheme or "https"
        url = urlunsplit((scheme, host, "/".join(parts), q, ""))
    except Exception:
        url = url.replace(" ", "%20")
    return url


def _ident_from_url(url: str, title: str | None = None) -> str:
    path = unquote(urlsplit(url).path)
    q = urlsplit(url).query or ""
    m = re.search(r"download=\d+:([^&]+)", q, re.I)
    if m:
        return re.sub(r"\W+", "-", unquote(m.group(1))).strip("-").lower()[:160]
    if title:
        t = re.sub(r"\W+", "-", title).strip("-").lower()[:100]
        if t and len(t) > 8:
            return t
    name = Path(path).name or path
    stem = Path(name).stem
    return re.sub(r"\W+", "-", stem).strip("-").lower()[:160] or re.sub(r"\W+", "-", url)[-80:]


def _is_diario(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    path = unquote(urlsplit(url).path).lower()
    if any(x in host for x in ("jornal", "diario", "imprensa")):
        return path.endswith(".pdf") or "/files/" in path or "diario" in path or "jornal" in path
    return bool(re.search(r"(?i)(di[aá]rio.?da.?rep|jornal.?oficial|constituicao)", path))


def _is_download_pdf(url: str) -> bool:
    """Presidência (and similar) serve PDFs via ?download=N:slug without .pdf suffix."""
    q = (urlsplit(url).query or "").lower()
    if "download=" not in q:
        return False
    return bool(re.search(r"download=\d+:(?:decreto|lei|diploma|resolu|regulamento|portaria|despacho)", q, re.I))


def _keep(url: str, title: str | None = None) -> bool:
    if not _host_ok(url):
        return False
    blob = unquote(urlsplit(url).path) + " " + url + " " + (title or "")
    if DROP_RE.search(blob):
        return False
    low = url.lower().split("?")[0]
    path = unquote(urlsplit(url).path).lower()
    is_pdf = path.endswith(".pdf") or low.endswith(".pdf") or _is_download_pdf(url)
    if not is_pdf:
        return False
    if any(x in path for x in ("/css/", "favicon", "apple-touch", ".css", "webmanifest", "/js/")):
        return False
    if _is_diario(url) or _is_download_pdf(url):
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
                    ["tesseract", str(img), "stdout", "-l", "por+fra+spa", "--psm", "6"],
                    check=False, capture_output=True, timeout=120,
                )
                if tproc.returncode == 0 and tproc.stdout:
                    chunks.append(tproc.stdout.decode("utf-8", "replace").strip())
            return "\n\n".join(c for c in chunks if c).strip()
    except Exception as exc:
        log.warning("ocr_pdf: %s", exc)
        return ""


def fetch_st(url: str, wayback_ts: str | None = None) -> dict:
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
    raw = (url or "").split("#")[0].strip()
    url = _norm_url(raw)
    if not url or not _keep(url, title=title):
        return
    q = urlsplit(url).query or ""
    m = re.search(r"download=(\d+):([^&]+)", q, re.I)
    if m:
        key = f"pres-dl-{m.group(1)}"
        if not title:
            title = unquote(m.group(2)).replace("-", " ")
        if not ident or ident.startswith("documentos") or ident.startswith("index"):
            ident = unquote(m.group(2))
        # Prefer Portuguese path variant
        if key in seen:
            return
        # boost pt
        if "/pt/" in url.lower():
            priority = min(priority, 9)
    else:
        key = url.lower().split("?")[0].replace("://www.", "://").replace("http://", "https://")
        if key in seen:
            return
    if size_hint and size_hint > MAX_PDF_BYTES:
        return
    seen.add(key)
    ident = re.sub(r"\W+", "-", (ident or _ident_from_url(url, title)).strip("-")).lower()[:160]
    # Prefer raw URL (often http) for Wayback hit rate when CDX gave http
    fetch_url = raw if raw.startswith("http") else url
    items.append((priority, ident, fetch_url, ts, size_hint, title))


def discover():
    items = []
    seen = set()

    # Optional deepen seeds (JSON list of {url,ts,ident,priority,len}) written by expand probes
    seed_file = Path("/tmp/st_seeds_final.json")
    if seed_file.is_file():
        try:
            import json as _json
            for row in _json.loads(seed_file.read_text()):
                u = row.get("url") or ""
                ts = (row.get("ts") or "")[:14] or None
                pri = int(row.get("priority") or 12)
                ident = row.get("ident") or _ident_from_url(u)
                try:
                    length = int(row.get("len") or 0) or None
                except Exception:
                    length = None
                _add(items, seen, ident, u, ts=ts, priority=pri, size_hint=length, title=row.get("ident"))
            log.info("seed_file loaded %s", seed_file)
        except Exception as exc:
            log.info("seed_file %s", exc)

    for seed in SEED_PDFS:
        pri = 5 if re.search(r"(?i)(constitu)", seed) else 8
        _add(items, seen, _ident_from_url(seed), seed, ts=None, priority=pri)

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
                if ".pdf" in full.lower() or "/files/" in full.lower() or "/uploads/" in full.lower():
                    pri = 15
                    low = unquote(full).lower()
                    if re.search(r"(?i)(constitu)", low):
                        pri = 5
                    elif re.search(r"(?i)(lei|decreto|codigo|regulamento)", low):
                        pri = 10
                    elif _is_diario(full):
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
                        "lei", "leis", "decreto", "constitu", "diario", "jornal",
                        "texto", "documento", "download", "upload", "files",
                        "legisl", "regulamento", "norma", "ficheiros",
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
                    for href in re.findall(r"""href=["']([^"']+)["']""", t2, re.I):
                        full = urljoin(sub_url, html_lib.unescape(href))
                        if ".pdf" in full.lower() or "/files/" in full.lower() or "/uploads/" in full.lower():
                            pri = 16
                            low = unquote(full).lower()
                            if re.search(r"(?i)(constitu)", low):
                                pri = 5
                            elif re.search(r"(?i)(lei|decreto|codigo)", low):
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
                limit=env_int("CDX_LIMIT", 400),
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
                    limit=env_int("CDX_LIMIT", 400),
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
            if re.search(r"(?i)(constitu)", low):
                pri = 5
            elif _is_diario(orig):
                pri = 14
            elif re.search(r"(?i)(lei|codigo|regulamento)", low):
                pri = 12
            elif re.search(r"(?i)(decreto|diploma|resolu|portaria|despacho)", low):
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
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "host_not_st"})
            continue
        got = fetch_st(url, wayback_ts=ts)
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
        if not TEXT_KEEP_RE.search(text[:8000]) and not _is_diario(url):
            if not re.search(r"(?i)(lei|decreto|constitu|codigo|regulamento|diploma)", ident):
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
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_st.py",
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
        source="São Tomé and Príncipe (governo.st / Assembleia / Presidência / Justiça / Finanças / Diário)",
        source_urls=[
            "https://www.governo.st/",
            "https://www.assembleia.st/",
            "https://www.presidencia.st/",
            "https://justica.gov.st/",
            "https://financas.gov.st/",
            "https://www.gov.st/",
            "https://www.bcstp.st/",
            "https://www.ine.st/",
        ],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (live crawl *.st / *.gov.st + CDX PDF / Diário)",
        notes=(
            "Official *.st / *.gov.st lei/decreto/constituição PDFs only "
            "(São Tomé and Príncipe). OCR por+fra+spa for scans. "
            "Not AfricanLII. No WAF bypass. Not legal advice. "
            "st=São Tomé and Príncipe (not Equatorial Guinea/gq, not Gabon/ga, not Angola/ao)."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s total_instruments=%s", ok, skip, fail, len(done))


if __name__ == "__main__":
    main()
