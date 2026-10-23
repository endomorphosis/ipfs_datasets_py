#!/usr/bin/env python3
"""Guinea / Guinee (gn): official law / JO PDFs from *.gov.gn / *.gouv.gn.

Official only (Republique de Guinee — NOT Equatorial Guinea, NOT Guinea-Bissau, NOT Papua New Guinea):
  - https://journal-officiel.sgg.gov.gn/  (Journal Officiel — /JO/*.pdf live)
  - https://sgg.gov.gn/ / www.sgg.gov.gn (document/downloadfile)
  - https://cnt.gov.gn/ (CNT textes/lois + archive.assemblee Loi*.pdf)
  - mines.gov.gn / agriculture.gov.gn / primature.gov.gn / mef.gov.gn / gouvernement.gov.gn
  - Wayback/CDX of the same official *.gov.gn / *.gouv.gn URLs

Filter: JO fascicules kept; other hosts require loi/ordonnance/decret/constitution/code/charte.
Skip PDFs >12MB. Not AfricanLII / Droit-Afrique. No WAF bypass. Not legal advice.
NOTE: country code gn = Guinea (not Equatorial Guinea gq / Guinea-Bissau gw / Papua New Guinea pg).
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

CC, COUNTRY, LANG = "gn", "Guinea", "fr"
SOURCE_TYPE = "sgg_guinea_journal_officiel"
LICENSE = (
    "Republique de Guinee — Secretariat general du Gouvernement (sgg.gov.gn) / "
    "Journal Officiel (journal-officiel.sgg.gov.gn) / Conseil National de la Transition (cnt.gov.gn) / "
    "Ministeres (mines, agriculture, justice, primature, mef). "
    "Authentic Journal Officiel / official text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://sgg.gov.gn/; Guinea=gn not GQ/GW/PG)"
ART = re.compile(r"(?im)^\s*((?:Article|Art\.?)\s+\d+[a-zA-Zº°]?)\b")
log = logging.getLogger("gn")

SGG = "https://sgg.gov.gn"
JO = "https://journal-officiel.sgg.gov.gn"
CNT = "https://cnt.gov.gn"
MAX_PDF_BYTES = 12 * 1024 * 1024

ALLOWED = (
    "sgg.gov.gn",
    "journal-officiel.sgg.gov.gn",
    "cnt.gov.gn",
    "mines.gov.gn",
    "agriculture.gov.gn",
    "justice.gov.gn",
    "primature.gov.gn",
    "mef.gov.gn",
    "finances.gov.gn",
    "budget.gov.gn",
    "gouvernement.gov.gn",
    "presidence.gov.gn",
    "gov.gn",
    "gouv.gn",
    "assemblee.gov.gn",
    "assemblee-nationale.gov.gn",
    "assembleenationale.gov.gn",
    "an.gov.gn",
    "coursupreme.gov.gn",
    "courconstitutionnelle.gov.gn",
    "portail.gov.gn",
)

KEEP_RE = re.compile(
    r"(loi|ordonnance|ordonn|d[eé]cret|decret|arr[eê]t[eé]|arrete|constitution|code|"
    r"journal.?officiel|\bjos?\b|\bjo\b|organique|r[eè]glement|charte|statut|"
    r"/jo/|/document/downloadfile|textes?-?et-?lois|"
    r"charte.?de.?la.?transition|guinee-jo|code_?minier)",
    re.I,
)
DROP_RE = re.compile(
    r"(africanlii|guineelii|droit-afrique|gazettes\.africa|law\.africa|"
    r"discours|allocution|communique|compte[-_ ]rendu|/ccm/|photo|banner|logo|cv[-_]|"
    r"biographie|rapport[-_ ]annuel|/rapport|rapport%20|presentation|organigramme|"
    r"newsletter|recrutement|facebook|twitter|linkedin|"
    r"lettre.?d.?info|affectation|appel.?d.?offres|\baaoi\b|"
    r"bulletin.?stat|bulletin-\d|/rap-a\d|avis-dappel|etude-de-faisabilite|"
    r"note-conceptuelle|programmation-budget|mission-et-attribution|classement|"
    r"equatorial|guinea-?bissau|papua|png\.gov|\.gov\.pg\b|\.gq\b|\.gw\b)",
    re.I,
)
TEXT_KEEP_RE = re.compile(
    r"\b(loi|ordonnance|d[eé]cret|decret|constitution|journal\s+officiel|"
    r"code|r[eé]publique\s+de\s+guin[eé]e|conseil\s+national\s+de\s+la\s+transition|"
    r"assembl[eé]e\s+nationale|pr[eé]sident\s+de\s+la\s+r[eé]publique|promulgue|"
    r"partie\s+officielle|charte\s+de\s+la\s+transition)\b",
    re.I,
)

SEED_PDFS = [
    # JO live fascicules (homepage + known gaps)
    "https://journal-officiel.sgg.gov.gn/JO/2025/guinee-jo-2025-07-sp.pdf",
    "https://journal-officiel.sgg.gov.gn/JO/2025/guinee-jo-2025-01.pdf",
    "https://journal-officiel.sgg.gov.gn/JO/2024/guinee-jo-2024-12.pdf",
    "https://journal-officiel.sgg.gov.gn/JO/2024/guinee-jo-2024-01.pdf",
    "https://journal-officiel.sgg.gov.gn/JO/2021/guinee-jo-2021-05.pdf",
    # CNT Assemblée archive lois (Wayback/CDX of official cnt.gov.gn)
    "https://cnt.gov.gn/archive.assemblee/www.assemblee.gov.gn/sites/default/files/Loi2021/Loi0001.pdf",
    "https://cnt.gov.gn/archive.assemblee/www.assemblee.gov.gn/sites/default/files/Loi2021/Loi0002.pdf",
    "https://cnt.gov.gn/archive.assemblee/www.assemblee.gov.gn/sites/default/files/Loi2021/Loi0003.pdf",
    "https://cnt.gov.gn/archive.assemblee/www.assemblee.gov.gn/sites/default/files/Loi2021/Loi0004.pdf",
    "https://cnt.gov.gn/archive.assemblee/www.assemblee.gov.gn/sites/default/files/Loi2021/Loi0005.pdf",
    "https://cnt.gov.gn/archive.assemblee/www.assemblee.gov.gn/sites/default/files/Loi2021/Loi0006.pdf",
    "https://cnt.gov.gn/archive.assemblee/www.assemblee.gov.gn/sites/default/files/Loi2021/Loi0007.pdf",
    "https://cnt.gov.gn/archive.assemblee/www.assemblee.gov.gn/sites/default/files/Loi2021/Loi0008.pdf",
    "https://cnt.gov.gn/archive.assemblee/www.assemblee.gov.gn/sites/default/files/Loi2021/Loi0009.pdf",
    "https://cnt.gov.gn/archive.assemblee/www.assemblee.gov.gn/sites/default/files/Loi2021/Loi0010.pdf",
    "https://cnt.gov.gn/archive.assemblee/www.assemblee.gov.gn/sites/default/files/Loi2021/Loi0011.pdf",
    "https://cnt.gov.gn/archive.assemblee/www.assemblee.gov.gn/sites/default/files/Loi2021/Loi0013.pdf",
    "https://cnt.gov.gn/archive.assemblee/www.assemblee.gov.gn/sites/default/files/Loi2021/Loi0014.pdf",
    "https://cnt.gov.gn/archive.assemblee/www.assemblee.gov.gn/sites/default/files/Loi2021/Loi0015.pdf",
    # mines.gov.gn codes / arretes / decrets (Wayback of official)
    "https://mines.gov.gn/wp-content/uploads/2023/08/Code_Minier_2011_amende_2013_bilingue_FR-EN.pdf",
    "https://mines.gov.gn/wp-content/uploads/2023/08/Arrete-Comite-Interministeriel-CAGF-FODEL-2019.pdf",
    "https://mines.gov.gn/wp-content/uploads/2023/08/Arrete-conjoint-FODEL-Novembre-2018.pdf",
    "https://mines.gov.gn/wp-content/uploads/2023/08/Arrete_2016_Droits_Fixes-et-Redevances_Mines-Guinee.pdf",
    "https://mines.gov.gn/wp-content/uploads/2023/08/Arrete_2018_application-Art165_Code-Minier_Transfert-Infranat.pdf",
    "https://mines.gov.gn/wp-content/uploads/2023/08/Decret-041-CNM.pdf",
    "https://mines.gov.gn/wp-content/uploads/2023/08/Decret-Portant-Gestion-des-Autorisations-et.pdf",
    "https://mines.gov.gn/wp-content/uploads/2023/08/Decret-Relatif-a-L-Application-Des-Dispositions.pdf",
    "https://mines.gov.gn/wp-content/uploads/2023/08/Decret_Creation_ANAFIC_2017.pdf",
    "https://mines.gov.gn/wp-content/uploads/2023/08/Guinee_CharteDeLaTransition270921_C0-1.pdf",
    "https://mines.gov.gn/wp-content/uploads/2025/12/JOURNAL_OFFICIEL_SIMANDOU_N02_-_102024.pdf",
    # agriculture
    "https://agriculture.gov.gn/wp-content/uploads/2023/01/Loi-056-G_SUR-LES-ETABLISSEMENTS-PUBLICS-1.pdf",
    "https://agriculture.gov.gn/wp-content/uploads/2025/06/LOI_ORDINAIRE_PORTANT_CODE_PASTORAL_A51-2.pdf",
    # presidence / primature charte + constitution
    "https://presidence.gov.gn/images/projetdenouvelleconstitution/NouvelleConstitution.pdf",
    "https://presidence.gov.gn/wp-content/uploads/2022/01/Guinee_CharteDeLaTransition270921_C0-1.pdf",
    "https://presidence.gov.gn/wp-content/uploads/2022/01/DECRET-001-DU-08-SEPT-2021-portant-promulgation-de-la-loi-de-finances-rectificative-exercice-2021.pdf",
    "https://primature.gov.gn/images/Guinee_CharteDeLaTransition270921_C0.pdf",
    # lean SGG CDX-proven downloadfile ids (Wayback)
    "https://sgg.gov.gn/document/downloadfile/50",
    "https://sgg.gov.gn/document/downloadfile/100",
    "https://www.sgg.gov.gn/document/downloadfile/50",
    "https://www.sgg.gov.gn/document/downloadfile/100",
]

LISTING_SPECS = [
    ("https://journal-officiel.sgg.gov.gn/", 1, 8),
    ("https://journal-officiel.sgg.gov.gn/JO/2025/", 1, 6),
    ("https://journal-officiel.sgg.gov.gn/JO/2024/", 1, 7),
    ("https://journal-officiel.sgg.gov.gn/JO/2023/", 1, 9),
    ("https://journal-officiel.sgg.gov.gn/JO/2022/", 1, 10),
    ("https://sgg.gov.gn/", 1, 20),
    ("https://www.sgg.gov.gn/", 1, 20),
    ("https://cnt.gov.gn/textes-et-lois-adoptes/", 2, 12),
    ("https://cnt.gov.gn/", 1, 15),
    ("https://mines.gov.gn/", 1, 35),
    ("https://agriculture.gov.gn/", 1, 40),
    ("https://primature.gov.gn/", 1, 40),
    ("https://presidence.gov.gn/", 1, 35),
    ("https://mef.gov.gn/", 1, 45),
]


def _host_ok(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    if host.endswith(".gq") or host.endswith(".gw") or host.endswith(".pg"):
        return False
    if any(x in host for x in ("africanlii", "guineelii", "droit-afrique", "gazettes.africa", "law.africa", "papua", "equatorial")):
        return False
    if DROP_RE.search(url):
        # still allow if clearly JO/loi path and host ok — DROP checked again in _keep
        pass
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
        if host.startswith("www."):
            bare = host[4:]
            if bare in (
                "sgg.gov.gn", "cnt.gov.gn", "mines.gov.gn", "agriculture.gov.gn",
                "justice.gov.gn", "primature.gov.gn", "mef.gov.gn",
                "gouvernement.gov.gn", "presidence.gov.gn",
                "journal-officiel.sgg.gov.gn",
            ):
                host = bare
        parts = []
        for seg in p.path.split("/"):
            if not seg:
                parts.append(seg)
                continue
            parts.append(seg if "%" in seg else quote(seg, safe="._-()[]',"))
        url = urlunsplit((p.scheme or "https", host, "/".join(parts), p.query, ""))
    except Exception:
        url = url.replace(" ", "%20")
    return url


def _ident_from_url(url: str) -> str:
    path = unquote(urlsplit(url).path)
    m = re.search(r"/document/downloadfile/(\d+)", path, re.I)
    if m:
        return f"sgg-doc-{m.group(1)}"
    m = re.search(r"/Loi(\d{4})/Loi(\d+)\.pdf", path, re.I)
    if m:
        return f"loi-{m.group(1)}-{m.group(2)}"
    name = Path(path).name or path
    stem = Path(name).stem
    low = path.lower()
    if "/jo/" in low or "guinee-jo" in low or "journal_officiel" in low:
        return "jo-" + re.sub(r"\W+", "", stem)[:48].lower()
    return re.sub(r"\W+", "-", stem).strip("-").lower()[:160] or re.sub(r"\W+", "-", url)[-80:]


def _is_jo(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    path = unquote(urlsplit(url).path).lower()
    if "journal-officiel.sgg.gov.gn" in host and ("/jo/" in path or path.endswith(".pdf")):
        if "/ccm/" in path:
            return False
        return True
    if "guinee-jo-" in path or "journal_officiel" in path:
        return True
    return False


def _keep(url: str) -> bool:
    if not _host_ok(url):
        return False
    if DROP_RE.search(url):
        return False
    path = unquote(urlsplit(url).path)
    low = (path + " " + url).lower()
    if "/document/downloadfile/" in low:
        return True
    if _is_jo(url):
        return low.endswith(".pdf")
    if "archive.assemblee" in low and low.endswith(".pdf"):
        # Lois only — exclude parliamentary "rapport" PDFs on same archive host
        fname = Path(unquote(urlsplit(url).path)).name.lower()
        if re.search(r"loi\d{2,}", fname) or re.search(r"/loi\d|/loi20", low):
            return True
        return False
    if not (low.endswith(".pdf") or "/downloadfile/" in low):
        return False
    host = (urlsplit(url).hostname or "").lower()
    if "mef.gov.gn" in host:
        return bool(re.search(r"(loi|code|ordonnance|d[eé]cret|decret|arr[eê]t|constitut|cgi|douane|imp[oô]t)", low))
    return bool(KEEP_RE.search(low))


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


def fetch_gn(url: str, wayback_ts: str | None = None) -> dict:
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
        low = full.lower()
        if ".pdf" in low or "/document/downloadfile/" in low:
            out.append(full.split("#")[0])
    for m in re.findall(r'(https?://[^\s"\'<>]+\.pdf)', html or "", re.I):
        out.append(m.split("#")[0])
    for m in re.findall(r'/JO/[^\s"\'<>]+\.pdf', html or "", re.I):
        out.append(urljoin(base, m))
    for m in re.findall(r'/document/downloadfile/\d+', html or "", re.I):
        out.append(urljoin(base, m))
    for m in re.findall(r'/wp-content/uploads/[^\s"\'<>]+\.pdf', html or "", re.I):
        out.append(urljoin(base, m))
    return out


def discover():
    items = []
    seen = set()

    for seed in SEED_PDFS:
        _add(items, seen, _ident_from_url(seed), seed, ts=None, priority=5)

    # Prefer CDX-backed SGG downloadfile (live often Cloudflare 202). Lean known-good ids only.
    for doc_id in (50, 100, 101, 102, 103, 104, 167, 171, 178, 180, 289, 296):
        url = f"{SGG}/document/downloadfile/{doc_id}"
        _add(items, seen, f"sgg-doc-{doc_id}", url, ts=None, priority=18)

    # CNT Loi2021 enumerate lean (official archive.assemblee paths; Wayback on fail)
    # Filenames observed in CDX: Loi0001..Loi0020 and Loi004..Loi009
    for name in [f"Loi{n:04d}.pdf" for n in range(1, 16)] + [f"Loi{n:03d}.pdf" for n in range(4, 10)]:
        url = f"{CNT}/archive.assemblee/www.assemblee.gov.gn/sites/default/files/Loi2021/{name}"
        _add(items, seen, _ident_from_url(url), url, ts=None, priority=9)

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
                    if "constitut" in low or "charte" in low:
                        p = 5
                    elif _is_jo(pdf) or "guinee-jo" in low:
                        p = min(p, 10)
                    elif re.search(r"(loi|code|ordonnance)", low):
                        p = min(p, 14)
                    _add(items, seen, _ident_from_url(pdf), pdf, ts=None, priority=p)
                    n += 1
                log.info("listing %s page=%s pdfs=%s", base.rstrip("/").split("/")[-1] or "home", page, n)
                if n == 0 and page > 0:
                    break
            except Exception as exc:
                log.info("listing %s %s", url, exc)
                break

    cdx_prefixes = (
        "journal-officiel.sgg.gov.gn/JO/",
        "journal-officiel.sgg.gov.gn/",
        "sgg.gov.gn/document/downloadfile/",
        "www.sgg.gov.gn/document/downloadfile/",
        "cnt.gov.gn/archive.assemblee/",
        "cnt.gov.gn/",
        "mines.gov.gn/wp-content/uploads/",
        "agriculture.gov.gn/wp-content/uploads/",
        "www.agriculture.gov.gn/wp-content/uploads/",
        "primature.gov.gn/images/",
        "www.primature.gov.gn/images/",
        "presidence.gov.gn/wp-content/uploads/",
        "presidence.gov.gn/images/",
        "www.presidence.gov.gn/images/",
        "mef.gov.gn/uploads/Codes/",
        "mef.gov.gn/wp-content/uploads/",
        "gouvernement.gov.gn/",
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
        if "downloadfile" in prefix or not hits:
            try:
                hits2 = cdx_urls(
                    prefix,
                    limit=env_int("CDX_LIMIT", 150),
                    match_type="prefix",
                    extra_filters=["statuscode:200"],
                ) or []
                hits = hits + hits2
            except Exception:
                pass
        for h in hits:
            orig = h.get("original") or ""
            ts = (h.get("timestamp") or "")[:14] or None
            try:
                length = int(h.get("length") or 0)
            except Exception:
                length = 0
            if length < 0:
                length = 0  # CDX sometimes returns bogus negative compressed sizes
            if length and length > MAX_PDF_BYTES:
                continue
            if not _keep(orig):
                continue
            pri = 28
            if _is_jo(orig):
                pri = 16
            if re.search(r"(?i)constitut|charte", orig):
                pri = 8
            if re.search(r"(?i)(loi|code|ordonnance)", unquote(orig)):
                pri = min(pri, 14)
            if "archive.assemblee" in unquote(orig).lower():
                pri = min(pri, 9)
            if re.search(r"(?i)(code_?minier|arrete|arr[eê]t|decret)", unquote(orig)):
                pri = min(pri, 12)
            if "/document/downloadfile/" in orig.lower():
                pri = min(pri, 22)
            _add(items, seen, _ident_from_url(orig), orig, ts=ts, priority=pri, size_hint=length or None)

    items.sort(key=lambda x: (x[0], x[1]))
    out_items = [(ident, url, ts, size) for _, ident, url, ts, size in items]
    log.info("catalog %s", len(out_items))
    return out_items


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
        got = fetch_gn(url, wayback_ts=ts)
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
            if not re.search(r"(?i)(loi|ordonnance|decret|constitut|code|jo-|charte|sgg-doc)", ident):
                fail += 1
                log_failure(CC, {"identifier": ident, "source_url": url, "reason": "text_not_legal"})
                continue
        head = text[:3000].lower()
        if re.search(r"equatorial\s+guinea|guinea[- ]bissau|papua\s+new\s+guinea|guinea\s+ecuatorial", head):
            if "republique de guinee" not in head and "république de guinée" not in head:
                fail += 1
                log_failure(CC, {"identifier": ident, "source_url": url, "reason": "wrong_guinea_country"})
                continue
        title = None
        for line in text.splitlines():
            if len(line.strip()) > 18:
                title = line.strip()[:240]
                break
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title or ident, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_gn.py",
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
        source="Guinea SGG / Journal Officiel (journal-officiel.sgg.gov.gn) / CNT (cnt.gov.gn)",
        source_urls=[
            "https://journal-officiel.sgg.gov.gn/",
            "https://sgg.gov.gn/",
            "https://cnt.gov.gn/textes-et-lois-adoptes/",
            "https://cnt.gov.gn/archive.assemblee/",
            "https://mines.gov.gn/",
            "https://agriculture.gov.gn/",
            "https://primature.gov.gn/",
            "https://presidence.gov.gn/",
        ],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (journal-officiel.sgg.gov.gn JO live + SGG downloadfile + CNT archive + ministry CDX)",
        notes="Official *.gov.gn / *.gouv.gn only. OCR fra for scans. Not AfricanLII. No WAF bypass. gn=Guinea (not GQ/GW/PG). Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s total_instruments=%s", ok, skip, fail, len(done))


if __name__ == "__main__":
    main()
