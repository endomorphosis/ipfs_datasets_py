#!/usr/bin/env python3
"""Equatorial Guinea / Guinea Ecuatorial (gq): official law / BOE PDFs from *.gob.gq / *.gq.

Official only (NOT Guinea gn / Guinea-Bissau gw / Gabon ga):
  - https://boe.gob.gq/ (Boletín Oficial del Estado)
  - https://minjusticia.gob.gq/ / minfuncionpublica.gob.gq / minhacienda.gob.gq
  - https://mintrabajo.gob.gq/ / minexteriores.gob.gq / anticorrupcion.gob.gq
  - https://primatura.gob.gq/ / www.gob.gq (→ guineaecuatorialpress.com official press)
  - https://www.guineaecuatorialpress.com/ (Página Oficial del Gobierno)
  - Wayback/CDX of the same official *.gob.gq / guineaecuatorialpress.com URLs

Filter: prefer ley/decreto/constitución/código/BOE/acuerdo; skip PDFs >12MB.
Not AfricanLII / Droit-Afrique. No WAF bypass. Not legal advice.
NOTE: country code gq = Equatorial Guinea / Guinea Ecuatorial (not gn, not gw, not ga).
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

CC, COUNTRY, LANG = "gq", "Equatorial Guinea", "es"
SOURCE_TYPE = "boe_guinea_ecuatorial_official"
LICENSE = (
    "República de Guinea Ecuatorial — BOE (boe.gob.gq) / Justicia / Función Pública / "
    "Hacienda / Trabajo / Exterior / Anticorrupción / Primatura / Página Oficial del "
    "Gobierno (gob.gq / guineaecuatorialpress.com) (*.gob.gq / *.gq). Authentic Boletín "
    "Oficial / official text prevails. Not legal advice. Not Guinea (gn) / Guinea-Bissau "
    "(gw) / Gabon (ga)."
)
UA = (
    "legal-corpora-collector/1.0 (research; source=https://boe.gob.gq/; "
    "EquatorialGuinea=gq not gn/gw/ga)"
)
ART = re.compile(r"(?im)^\s*((?:Artículo|Articulo|Art\.?)\s+\d+[a-zA-Zº°]?)\b")
log = logging.getLogger("gq")

MAX_PDF_BYTES = 12 * 1024 * 1024

ALLOWED = (
    "boe.gob.gq",
    "www.boe.gob.gq",
    "gob.gq",
    "www.gob.gq",
    "gov.gq",
    "www.gov.gq",
    "minjusticia.gob.gq",
    "www.minjusticia.gob.gq",
    "minfuncionpublica.gob.gq",
    "www.minfuncionpublica.gob.gq",
    "minhacienda.gob.gq",
    "www.minhacienda.gob.gq",
    "mintrabajo.gob.gq",
    "www.mintrabajo.gob.gq",
    "minexteriores.gob.gq",
    "www.minexteriores.gob.gq",
    "anticorrupcion.gob.gq",
    "www.anticorrupcion.gob.gq",
    "primatura.gob.gq",
    "www.primatura.gob.gq",
    "presidencia.gob.gq",
    "www.presidencia.gob.gq",
    "asamblea.gob.gq",
    "www.asamblea.gob.gq",
    "asambleanacional.gob.gq",
    "senado.gob.gq",
    "mininterior.gob.gq",
    "minsa.gob.gq",
    "mineduc.gob.gq",
    "minindustria.gob.gq",
    "minagricultura.gob.gq",
    "minpesca.gob.gq",
    "mincultur.gob.gq",
    "mintct.gob.gq",
    "minasig.gob.gq",
    "hsm.gob.gq",
    "www.hsm.gob.gq",
    "guineaecuatorialpress.com",
    "www.guineaecuatorialpress.com",
    "inege.gq",
    "www.inege.gq",
    "anif.gq",
    "www.anif.gq",
    "cniapge.gq",
    "www.cniapge.gq",
)

KEEP_RE = re.compile(
    r"(ley|decreto|ordenanza|orden.?ministerial|resoluci[oó]n|constituci[oó]n|"
    r"c[oó]digo|boletin|bolet[ií]n|bo\b|org[aá]nica|reglamento|estatuto|norma|"
    r"acuerdo|presupuesto|lpge|lfr|procedimiento|funcionarios|datos.?personales|"
    r"wp-content/uploads|/uploads/|/files/|/documents?/|"
    r"guinea.?ecuatorial|guineaecuatorial)",
    re.I,
)
DROP_RE = re.compile(
    r"(africanlii|droit-afrique|gazettes\.africa|law\.africa|"
    r"discurso|allocution|communique|comunicado|nota.?de.?prensa|notaprensa|photo|banner|logo|"
    r"cv[-_]|biograf[ií]a|organigrama|orgnigrama|presentacion|newsletter|"
    r"facebook|twitter|linkedin|album|actualites|licitacion|"
    r"lista_(?:malabo|bata|mongomo|luba|annobon|djibloho|ebibeyin|evinayong)|"
    r"lista.?diplomatica|guia.?misiones|anuario.?diplomatico|cuadrante.?medico|"
    r"documento.?de.?pruebas|carta\.pdf|meuramdum|memorando|informe.?pge|"
    r"liquidacion|oferta.?de.?empleo|postulantes|nombramie?ntos?|"
    r"pdge-guinea|partido.?democratico|"
    r"favicon|apple-touch|webmanifest|/css/|\.css\b|"
    r"ponencias|resumen_y_fotos|denunciaresponsable|1q2v_informe|sitrep|"
    r"boletinice|boletin.?ice|fondo.?para.?la.?internacionalizaci|"
    r"jubilacion|resulucion-de-jubilacion|competiciones|feguifut|gu[ií]a_?cumple|ingreso.?laboral|lista.?de.?exencion|jonathan|juanjesus|nota-de-prens|horarios|concurrencias|"
    r"\bconakry\b|\.gn/|\.gw/|bissau|guin[eé]e(?!\s+ecuatorial)|"
    r"gabon|\.ga/|brazzaville|\.cg/|kinshasa|\.cd/)",
    re.I,
)
TEXT_KEEP_RE = re.compile(
    r"\b(ley|decreto|ordenanza|constituci[oó]n|boletin|bolet[ií]n\s+oficial|"
    r"c[oó]digo|rep[uú]blica\s+de\s+guinea\s+ecuatorial|"
    r"asamblea\s+nacional|c[aá]mara\s+de\s+los\s+diputados|"
    r"presidente\s+de\s+la\s+rep[uú]blica|promulga|dispongo|"
    r"art[ií]culo|guinea\s+ecuatorial|acuerdo)\b",
    re.I,
)

# High-value known official law PDFs (live BOE + ministries)
SEED_PDFS = [
    "https://boe.gob.gq/files/LEY%20FUNDAMENTAL.pdf",
    "https://boe.gob.gq/files/LEY%20ORG%C3%81NICA%20DEL%20PODER%20JUDICIAL.pdf",
    "https://boe.gob.gq/files/Ley%20General%20de%20Educaci%C3%B3n.pdf",
    "https://boe.gob.gq/files/Decreto%20de%20Fijaci%C3%B3n%20de%20los%20D%C3%ADas%20Feriados%20en%20Guinea%20Ecuatorial.pdf",
    "https://boe.gob.gq/files/Decreto%20por%20el%20que%20se%20disminuye%20el%20capital%20minimo.pdf",
    "https://boe.gob.gq/files/ANTICORRUPCI%C3%93N.pdf",
    "https://boe.gob.gq/files/ADQUISICI%C3%93N%20DE%20TERRENOS%20POR%20PERSONAS%20F%C3%8DSICAS%20Y%20JUR%C3%8DDICAS%20EXTRANJERAS.pdf",
    "https://boe.gob.gq/files/COMISI%C3%93N%20ENCARGADA%20DE%20IDENTIFICAR%20TERRENOS%20EXPROPIABLES.pdf",
    "https://boe.gob.gq/files/GARANT%C3%8DA%20DE%20LA%20PROPIEDAD%20DE%20FINCAS%20R%C3%9ASTICAS.pdf",
    "https://boe.gob.gq/files/GOBIERNO%20DE%20LAS%20COMUNIDADES%20DE%20LA%20PROPIEDAD%20HORIZONTAL.pdf",
    "https://minfuncionpublica.gob.gq/wp-content/uploads/LEY-FUNDAMENTAL-DE-G.E..pdf",
    "https://minfuncionpublica.gob.gq/wp-content/uploads/LEY-numero-1-del-2004-SOBRE-LA-ETICA-Y-DIGNIDAD-EN-EL-EJERCICIO-DE-LA-FUNCION-PUBLICA.pdf",
    "https://minfuncionpublica.gob.gq/wp-content/uploads/LEY-numero-1-del-2014-SOBRE-PROCEDIMIENTO-ADMINISTRATIVO.pdf",
    "https://minfuncionpublica.gob.gq/wp-content/uploads/LEY-numero-1-del-2016-PROTECCION-DE-DATOS-PERSONALES.pdf",
    "https://minfuncionpublica.gob.gq/wp-content/uploads/LEY-numero-2-del-2014-SOBRE-FUNCIONARIOS-CIVILES-DEL-ESTADO-1.pdf",
    "https://minfuncionpublica.gob.gq/wp-content/uploads/LEY-numero-2-del-2015-REGIMEN-JURIDICO-DE-LA-ADMINISTRACION-GRAL-DEL-ESTADO.pdf",
    "https://minfuncionpublica.gob.gq/wp-content/uploads/LEY-numero-2-del-2016-SOBRE-LA-CONSERVACION-DE-DATOS.pdf",
    "https://minfuncionpublica.gob.gq/wp-content/uploads/LEY-numero-2-del-2017-SOBRE-FIRMAS-Y-DOCUMENTOS-ELECTRONICOS.pdf",
    "https://minfuncionpublica.gob.gq/wp-content/uploads/Ley_Reguladora_Entidades_Autonomas_y_Empresas_Publicas.pdf",
    "https://mintrabajo.gob.gq/wp-content/uploads/REFORMA-LEY-DE-TRABAJO-3.pdf",
    "https://anticorrupcion.gob.gq/wp-content/uploads/2024/10/DECRETO-SOBRE-ETICA-Y-DIGNIDAD.pdf",
    "https://anticorrupcion.gob.gq/wp-content/uploads/2024/10/LUCHA-CONTRA-LA-CORRUPCION.pdf",
    "https://hsm.gob.gq/wp-content/uploads/DIVULGACION-DE-LA-LEY-LABORAL.pdf",
]

HOMES = [
    "https://boe.gob.gq/",
    "https://boe.gob.gq/ultimaspublicaciones",
    "https://minjusticia.gob.gq/",
    "https://minjusticia.gob.gq/descargas/",
    "https://minfuncionpublica.gob.gq/",
    "https://mintrabajo.gob.gq/",
    "https://mintrabajo.gob.gq/descargas-ministerio/constitucion/",
    "https://mintrabajo.gob.gq/descargas-ministerio/leyes-organicas/",
    "https://minexteriores.gob.gq/",
    "https://anticorrupcion.gob.gq/",
    "https://primatura.gob.gq/",
    "https://www.gob.gq/",
    "https://www.guineaecuatorialpress.com/",
    "https://hsm.gob.gq/",
    # minhacienda live is often compromised; still try + rely on CDX
    "https://minhacienda.gob.gq/",
]

CDX_PREFIXES = (
    "boe.gob.gq/",
    "boe.gob.gq/files/",
    "minfuncionpublica.gob.gq/",
    "www.minfuncionpublica.gob.gq/",
    "minhacienda.gob.gq/",
    "www.minhacienda.gob.gq/",
    "mintrabajo.gob.gq/",
    "www.mintrabajo.gob.gq/",
    "minexteriores.gob.gq/",
    "www.minexteriores.gob.gq/",
    "anticorrupcion.gob.gq/",
    "www.anticorrupcion.gob.gq/",
    "minjusticia.gob.gq/",
    "primatura.gob.gq/",
    "hsm.gob.gq/",
    "guineaecuatorialpress.com/",
    "www.guineaecuatorialpress.com/",
    "guineaecuatorialpress.com/imgdb/",
    "www.guineaecuatorialpress.com/imgdb/",
    "gob.gq/",
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
            "pdge-guinea",
        )
    ):
        return False
    # Never harvest Guinea (gn), Guinea-Bissau (gw), Gabon (ga), Congo
    if host.endswith((".gn", ".gw", ".ga", ".cg", ".cd", ".st")):
        return False
    if any(x in host for x in ("conakry", "bissau", "brazzaville", "kinshasa", "gabon")):
        return False
    # Allow *.gob.gq, selected *.gq, and official press
    if host.endswith(".gob.gq") or host in ("gob.gq", "gov.gq"):
        return True
    if host in (
        "guineaecuatorialpress.com",
        "www.guineaecuatorialpress.com",
        "inege.gq",
        "www.inege.gq",
        "anif.gq",
        "www.anif.gq",
        "cniapge.gq",
        "www.cniapge.gq",
    ):
        return True
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


def _is_boe(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    path = unquote(urlsplit(url).path).lower()
    if not (host.startswith("boe.") or "boe.gob.gq" in host):
        return bool(re.search(r"(?i)(ley.?fundamental|boletin.?oficial)", path))
    return path.endswith(".pdf") or "/files/" in path or "bolet" in path


def _keep(url: str, title: str | None = None) -> bool:
    if not _host_ok(url):
        return False
    blob = unquote(urlsplit(url).path) + " " + url + " " + (title or "")
    if DROP_RE.search(blob):
        return False
    low = url.lower().split("?")[0]
    path = unquote(urlsplit(url).path).lower()
    # Strict: PDF only (no CSS/favicon/webmanifest under Drupal /files/)
    if not (path.endswith(".pdf") or low.endswith(".pdf")):
        return False
    if any(x in path for x in ("/css/", "favicon", "apple-touch", ".css", "webmanifest", "/js/")):
        return False
    host = (urlsplit(url).hostname or "").lower()
    if "guineaecuatorialpress.com" in host:
        # Official press: only PDFs whose filename looks like legislation
        name = Path(unquote(urlsplit(url).path)).name
        return bool(re.search(
            r"(?i)(ley|decreto|constituci|fundamental|resoluci|ordenanza|codigo|organica|acuerdo)",
            name,
        ))
    if _is_boe(url):
        return True
    # Treaties / agreements from foreign ministry — agreements only, not press notes
    if "minexteriores" in host:
        name = Path(unquote(urlsplit(url).path)).name
        return bool(re.search(r"(?i)(acuerdo|ley|decreto|tratado|convenio)", name))
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
                    ["tesseract", str(img), "stdout", "-l", "spa+fra+por", "--psm", "6"],
                    check=False, capture_output=True, timeout=120,
                )
                if tproc.returncode == 0 and tproc.stdout:
                    chunks.append(tproc.stdout.decode("utf-8", "replace").strip())
            return "\n\n".join(c for c in chunks if c).strip()
    except Exception as exc:
        log.warning("ocr_pdf: %s", exc)
        return ""


def fetch_gq(url: str, wayback_ts: str | None = None) -> dict:
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
    log.info("OCR spa %s bytes=%s", _ident_from_url(url)[:40], len(body))
    ocr = ocr_pdf(body)
    if len(ocr) >= 120:
        got.update(status="success", text=ocr, content=body, method="ocr_spa")
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
        pri = 5 if re.search(r"(?i)(fundamental|constituci)", seed) else 8
        _add(items, seen, _ident_from_url(seed), seed, ts=None, priority=pri)

    for home in HOMES:
        try:
            r = live_get(home, ua=UA, verify=False, timeout=(12, 40), retries=1)
            if getattr(r, "status_code", 0) != 200:
                log.info("home status=%s %s", getattr(r, "status_code", None), home)
                continue
            # Skip compromised parking pages (e.g. minhacienda spam)
            text = r.text or ""
            if re.search(r"(?i)(celtabet|gambling|casino|bet365)", text[:2000]):
                log.info("home compromised/skip %s", home)
                continue
            n = 0
            for href in re.findall(r"""href=["']([^"']+)["']""", text, re.I):
                full = urljoin(home, html_lib.unescape(href))
                if ".pdf" in full.lower() or "/files/" in full.lower() or "/imgdb/" in full.lower():
                    pri = 15
                    low = unquote(full).lower()
                    if re.search(r"(?i)(constituci|fundamental)", low):
                        pri = 5
                    elif re.search(r"(?i)(ley|decreto|codigo|organica)", low):
                        pri = 10
                    elif _is_boe(full):
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
                        "ley", "leyes", "decreto", "constituci", "boletin", "boe",
                        "texto", "documento", "download", "upload", "files",
                        "descargas", "legisl", "organica", "norma", "imgdb",
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
                        if ".pdf" in full.lower() or "/files/" in full.lower():
                            pri = 16
                            low = unquote(full).lower()
                            if re.search(r"(?i)(constituci|fundamental)", low):
                                pri = 5
                            elif re.search(r"(?i)(ley|decreto|codigo)", low):
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
            if re.search(r"(?i)(constituci|fundamental)", low):
                pri = 5
            elif _is_boe(orig):
                pri = 14
            elif re.search(r"(?i)(ley|organica|codigo)", low):
                pri = 12
            elif re.search(r"(?i)(decreto|ordenanza|resoluci)", low):
                pri = 20
            elif re.search(r"(?i)acuerdo", low):
                pri = 22
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
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "host_not_gq"})
            continue
        got = fetch_gq(url, wayback_ts=ts)
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
        if not TEXT_KEEP_RE.search(text[:8000]) and not _is_boe(url):
            if not re.search(r"(?i)(ley|decreto|constituci|fundamental|codigo|acuerdo|organica)", ident):
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
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_gq.py",
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
        source="Equatorial Guinea / Guinea Ecuatorial (boe.gob.gq / Justicia / Función Pública / Hacienda / Exterior / BOE)",
        source_urls=[
            "https://boe.gob.gq/",
            "https://minjusticia.gob.gq/",
            "https://minfuncionpublica.gob.gq/",
            "https://mintrabajo.gob.gq/",
            "https://minexteriores.gob.gq/",
            "https://anticorrupcion.gob.gq/",
            "https://primatura.gob.gq/",
            "https://www.guineaecuatorialpress.com/",
            "https://www.gob.gq/",
        ],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (live crawl *.gob.gq / guineaecuatorialpress.com + CDX PDF / BOE)",
        notes=(
            "Official *.gob.gq / guineaecuatorialpress.com BOE/ley/decreto PDFs only "
            "(Equatorial Guinea / Guinea Ecuatorial). OCR spa+fra+por for scans. "
            "Not AfricanLII. No WAF bypass. Not legal advice. "
            "gq=Equatorial Guinea (not Guinea/gn, not Guinea-Bissau/gw, not Gabon/ga)."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s total_instruments=%s", ok, skip, fail, len(done))


if __name__ == "__main__":
    main()
