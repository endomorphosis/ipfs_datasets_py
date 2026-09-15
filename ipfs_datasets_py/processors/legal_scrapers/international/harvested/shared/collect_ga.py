#!/usr/bin/env python3
"""Gabon (ga): official law / JO PDFs from *.ga / *.gouv.ga.

Official only:
  - https://sgg.ga/ (Secrétariat Général du Gouvernement)
  - https://presidence.ga/
  - https://www.assemblee.ga/ / assemblee.ga
  - primature / finances / justice / gouvernement / journal-officiel (*.ga / *.gouv.ga)
  - Wayback/CDX of the same official *.ga / *.gouv.ga URLs

Filter: prefer loi/ordonnance/décret/constitution/code/JO; skip PDFs >12MB.
Not AfricanLII / Droit-Afrique. No WAF bypass. Not legal advice.
NOTE: country code ga = Gabon (not Congo-Brazzaville cg, not DRC cd, not Equatorial Guinea).
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

CC, COUNTRY, LANG = "ga", "Gabon", "fr"
SOURCE_TYPE = "jo_gabon_official"
LICENSE = (
    "République Gabonaise — SGG (sgg.ga) / Présidence (presidence.ga) / "
    "Assemblée nationale (assemblee.ga) / Primature / Finances / Justice / "
    "Gouvernement / Journal Officiel (*.ga / *.gouv.ga). Authentic Journal "
    "Officiel / official text prevails. Not legal advice. Not Congo-Brazzaville "
    "(cg) / DRC (cd) / Equatorial Guinea."
)
UA = (
    "legal-corpora-collector/1.0 (research; source=https://sgg.ga/; "
    "Gabon=ga not cg/cd/gq)"
)
ART = re.compile(r"(?im)^\s*((?:Article|Art\.?)\s+\d+[a-zA-Zº°]?)\b")
log = logging.getLogger("ga")

MAX_PDF_BYTES = 12 * 1024 * 1024

ALLOWED = (
    "sgg.ga",
    "www.sgg.ga",
    "sgg.gouv.ga",
    "www.sgg.gouv.ga",
    "gouv.ga",
    "www.gouv.ga",
    "gov.ga",
    "www.gov.ga",
    "gouvernement.ga",
    "www.gouvernement.ga",
    "gouvernement.gouv.ga",
    "primature.ga",
    "www.primature.ga",
    "primature.gouv.ga",
    "www.primature.gouv.ga",
    "presidence.ga",
    "www.presidence.ga",
    "presidence.gouv.ga",
    "www.presidence.gouv.ga",
    "assemblee.ga",
    "www.assemblee.ga",
    "assemblee-nationale.ga",
    "www.assemblee-nationale.ga",
    "assembleenationale.ga",
    "www.assembleenationale.ga",
    "an.ga",
    "an.gouv.ga",
    "senat.ga",
    "www.senat.ga",
    "senat.gouv.ga",
    "finances.gouv.ga",
    "www.finances.gouv.ga",
    "finances.ga",
    "economie.gouv.ga",
    "www.economie.gouv.ga",
    "budget.gouv.ga",
    "www.budget.gouv.ga",
    "justice.gouv.ga",
    "www.justice.gouv.ga",
    "justice.ga",
    "www.justice.ga",
    "journal-officiel.ga",
    "www.journal-officiel.ga",
    "journalofficiel.ga",
    "www.journalofficiel.ga",
    "journalofficiel.gouv.ga",
    "www.journalofficiel.gouv.ga",
    "jo.gouv.ga",
    "www.jo.gouv.ga",
    "jo.ga",
    "lois.gouv.ga",
    "www.lois.gouv.ga",
    "dgi.ga",
    "www.dgi.ga",
    "dgi.gouv.ga",
    "courconstitutionnelle.ga",
    "www.courconstitutionnelle.ga",
    "cour-constitutionnelle.ga",
    "travail.gouv.ga",
    "mines.gouv.ga",
    "petrole.gouv.ga",
    "habitat.gouv.ga",
    "sante.gouv.ga",
    "education.gouv.ga",
    "interieur.gouv.ga",
    "environnement.gouv.ga",
    "eaux-forets.gouv.ga",
    "communication.gouv.ga",
    "numerique.gouv.ga",
)

KEEP_RE = re.compile(
    r"(loi|ordonnance|ordonn|d[eé]cret|decret|arr[eê]t[eé]|arrete|constitution|code|"
    r"journal.?officiel|\bjos?\b|\bjo\b|organique|r[eè]glement|charte|statut|"
    r"wp-content/uploads|/uploads/|/documents?/|/jo/|textes?|"
    r"gabon|gabonaise|"
    r"l[_\-]?f[_\-]?r|loi.?de.?finances|hydrocarb|minier|forestier|"
    r"ohada|cima|cemac|comptable|trait[eé]|investissement|"
    r"object\.getobject\.do)",
    re.I,
)
DROP_RE = re.compile(
    r"(africanlii|gabonlii|droit-afrique|gazettes\.africa|law\.africa|"
    r"discours|allocution|communique|photo|banner|logo|cv[-_]|"
    r"biographie|rapport[-_ ]annuel|presentation|organigramme|"
    r"newsletter|recrutement|facebook|twitter|linkedin|"
    r"album|actualites|appel.?d.?offres|"
    r"kinshasa|brazzaville|\.cd/|\.cg/|journalofficiel\.cd|presidence\.cd|"
    r"equatorial|guinea|malabo|\.gq|"
    r"depliant|formulaire|plaquette|catalogue|enquete|"
    r"\bID\d{2}[_-]|\bCA\d{2}[_-]|\bDO[-_]?\d{2}|\bTD\d{2}[_-]|"
    r"demande[-_ ]de|acompte|bordereau|bulletin[-_ ]de[-_ ]justification|"
    r"certificat[-_ ]dge|calendrier[-_ ]fiscal|immatriculation|"
    r"dgiprod|dsfcatalogue|dsftarifs)",
    re.I,
)
TEXT_KEEP_RE = re.compile(
    r"\b(loi|ordonnance|d[eé]cret|decret|arr[eê]t[eé]|constitution|journal\s+officiel|"
    r"code|r[eé]publique\s+gabonaise|assembl[eé]e\s+nationale|"
    r"pr[eé]sident\s+de\s+la\s+r[eé]publique|promulgue|partie\s+officielle|"
    r"conseil\s+des\s+ministres|gabon|ohada|acte\s+uniforme|cemac|cima|"
    r"charte|trait[eé]|hydrocarbures|code\s+minier|finances)\b",
    re.I,
)

SEED_PDFS = [
    # Deepen pass: official *.ga / *.gouv.ga PDFs known from CDX (live often 404)
    "https://www.dgi.ga/IMG/pdf/CEMAC_Charte_Investissements.pdf",
    "https://www.dgi.ga/IMG/pdf/Gabon_Recherche_Exploitations_Hydrocarbures.pdf",
    "https://www.dgi.ga/IMG/pdf_Arrete_111.pdf",
    "https://www.dgi.ga/IMG/pdf_Decret_122-PR-MECIT.pdf",
    "https://www.dgi.ga/IMG/pdf_Loi_4-85_du_27-06-1985_relative_aux_LF.pdf",
    "https://gouvernement.ga/wp-content/uploads/2025/11/Constitution-du-19-decembre-2024-de-la-republique-gabonaise.pdf",
    "https://www.dgi.ga/IMG/pdf/2004_L_F_R.pdf",
    "https://www.dgi.ga/IMG/pdf/2005__L_F_R.pdf",
    "https://www.dgi.ga/IMG/pdf/2006__L_F_R.pdf",
    "https://www.dgi.ga/IMG/pdf/DROIT_COMPTABLE.pdf",
    "https://www.dgi.ga/IMG/pdf/CIMA_Traite_CIMA.pdf",
    "https://www.dgi.ga/IMG/pdf/CEMAC_Agrement_etablissements_de_credit.pdf",
    "https://www.dgi.ga/IMG/pdf/OHADA_-_AU_Droit_commercial.pdf",
    "https://www.dgi.ga/IMG/pdf/OHADA_-_AU_Procedures_coll.pdf",
    "https://www.dgi.ga/IMG/pdf/OHADA_-_AU_Societes.pdf",
    "https://www.dgi.ga/IMG/pdf/OHADA_Comptabilite_des_entreprises.pdf",
]

HOMES = [
    "https://sgg.ga/",
    "https://www.sgg.ga/",
    "https://presidence.ga/",
    "https://www.presidence.ga/",
    "https://assemblee.ga/",
    "https://www.assemblee.ga/",
    "https://assemblee-nationale.ga/",
    "https://www.assemblee-nationale.ga/",
    "https://senat.ga/",
    "https://www.senat.ga/",
    "https://primature.gouv.ga/",
    "https://www.primature.gouv.ga/",
    "https://finances.gouv.ga/",
    "https://www.finances.gouv.ga/",
    "https://justice.gouv.ga/",
    "https://www.justice.gouv.ga/",
    "https://gouvernement.ga/",
    "https://www.gouvernement.ga/",
    "https://journal-officiel.ga/",
    "https://www.journal-officiel.ga/",
    "https://journalofficiel.ga/",
    "https://courconstitutionnelle.ga/",
    "https://sgg.gouv.ga/",
]

CDX_PREFIXES = (
    "sgg.ga/",
    "www.sgg.ga/",
    "sgg.gouv.ga/",
    "www.sgg.gouv.ga/",
    "gouv.ga/",
    "www.gouv.ga/",
    "gouvernement.ga/",
    "www.gouvernement.ga/",
    "primature.gouv.ga/",
    "www.primature.gouv.ga/",
    "presidence.ga/",
    "www.presidence.ga/",
    "presidence.gouv.ga/",
    "assemblee.ga/",
    "www.assemblee.ga/",
    "assemblee-nationale.ga/",
    "www.assemblee-nationale.ga/",
    "assembleenationale.ga/",
    "senat.ga/",
    "www.senat.ga/",
    "finances.gouv.ga/",
    "www.finances.gouv.ga/",
    "economie.gouv.ga/",
    "budget.gouv.ga/",
    "justice.gouv.ga/",
    "www.justice.gouv.ga/",
    "justice.ga/",
    "journal-officiel.ga/",
    "www.journal-officiel.ga/",
    "journalofficiel.ga/",
    "journalofficiel.gouv.ga/",
    "jo.gouv.ga/",
    "jo.ga/",
    "lois.gouv.ga/",
    "dgi.ga/",
    "www.dgi.ga/",
    "courconstitutionnelle.ga/",
    "www.courconstitutionnelle.ga/",
    "travail.gouv.ga/",
    "mines.gouv.ga/",
    "petrole.gouv.ga/",
    "environnement.gouv.ga/",
)


def _host_ok(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    if any(
        x in host
        for x in (
            "africanlii",
            "gabonlii",
            "droit-afrique",
            "gazettes.africa",
            "law.africa",
        )
    ):
        return False
    # Never harvest Congo-Brazzaville (cg), DRC (cd), Equatorial Guinea (gq)
    if host.endswith(".cd") or host.endswith(".cg") or host.endswith(".gq"):
        return False
    if "kinshasa" in host or "brazzaville" in host or "equatorial" in host:
        return False
    if not (host.endswith(".ga") or host == "ga"):
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
        path = "/".join(parts)
        query = ""
        # Preserve Alfresco-style PDF download ids (object.getObject.do?id=N)
        if "object.getobject.do" in path.lower():
            from urllib.parse import parse_qs, urlencode
            qs = parse_qs(p.query, keep_blank_values=False)
            oid = (qs.get("id") or [None])[0]
            if oid:
                # Canonical short form works on Wayback + many live mirrors
                query = urlencode({"id": oid, "object": "file", "mime": "file-mime"})
                # Collapse path to /object.getObject.do
                path = "/object.getObject.do"
        url = urlunsplit((p.scheme or "https", host, path, query, ""))
    except Exception:
        url = url.replace(" ", "%20")
    return url


def _ident_from_url(url: str, title: str | None = None) -> str:
    parts = urlsplit(url)
    path = unquote(parts.path)
    if "object.getobject.do" in path.lower():
        from urllib.parse import parse_qs
        oid = (parse_qs(parts.query).get("id") or ["x"])[0]
        host = (parts.hostname or "ga").lower().replace("www.", "").replace(".", "-")
        return f"{host}-obj-{oid}"[:160]
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
        or "journal-officiel" in host
        or host.startswith("jo.")
        or host == "jo.ga"
        or "/jo/" in path
        or "journal-officiel" in path
        or re.search(r"(?i)(jo[-_]?\d|journal.?officiel)", path)
        or ("sgg.ga" in host and re.search(r"(?i)(jo|journal)", path))
    )


def _keep(url: str, title: str | None = None) -> bool:
    if not _host_ok(url):
        return False
    blob = unquote(urlsplit(url).path) + " " + url + " " + (title or "")
    if DROP_RE.search(blob):
        return False
    low = url.lower().split("?")[0]
    is_obj = "object.getobject.do" in low
    if not (low.endswith(".pdf") or "/download" in low or "/document/" in low or is_obj):
        return False
    if is_obj:
        # Opaque CMS PDF downloads — accept; TEXT_KEEP_RE filters post-fetch
        return True
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


def fetch_ga(url: str, wayback_ts: str | None = None) -> dict:
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
    # Keep ?id= for object.getObject so distinct docs are not collapsed
    if "object.getobject.do" in url.lower():
        key = url.lower()
    else:
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
            host = (urlsplit(orig).hostname or "").lower()
            if "constitut" in low:
                pri = 5
            elif _is_jo(orig):
                pri = 14
            elif re.search(r"(?i)(loi|ordonnance|code)", low):
                pri = 12
            elif re.search(r"(?i)(decret|d[eé]cret|arrete)", low):
                pri = 20
            elif "object.getobject.do" in low:
                # Opaque CMS PDFs: prefer justice/mines; demote budget/economie noise
                if "justice" in host:
                    pri = 18
                elif "mines" in host or "petrole" in host:
                    pri = 22
                elif "primature" in host:
                    pri = 24
                elif "budget" in host or "economie" in host:
                    pri = 36
                else:
                    pri = 30
            _add(items, seen, _ident_from_url(_norm_url(orig)), orig, ts=ts, priority=pri, size_hint=length or None)

    # Cap opaque CMS object downloads (many are non-law); keep best priorities
    obj_max = env_int("OBJ_MAX", 55)
    objs = [it for it in items if "object.getobject.do" in (it[2] or "").lower()]
    non = [it for it in items if "object.getobject.do" not in (it[2] or "").lower()]
    objs.sort(key=lambda x: (x[0], x[1]))
    if len(objs) > obj_max:
        log.info("cap object.getObject %s -> %s", len(objs), obj_max)
        objs = objs[:obj_max]
    items = non + objs
    items.sort(key=lambda x: (x[0], x[1]))
    out = [(ident, url, ts, size, title) for _, ident, url, ts, size, title in items]
    log.info("catalog %s (obj=%s)", len(out), len(objs))
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
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "host_not_ga"})
            continue
        got = fetch_ga(url, wayback_ts=ts)
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
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_ga.py",
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
        source="Gabon / République Gabonaise (sgg.ga / Présidence / Assemblée / Primature / Finances / JO)",
        source_urls=[
            "https://sgg.ga/",
            "https://presidence.ga/",
            "https://www.assemblee.ga/",
            "https://primature.gouv.ga/",
            "https://finances.gouv.ga/",
            "https://justice.gouv.ga/",
            "https://gouvernement.ga/",
            "https://journal-officiel.ga/",
        ],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (live crawl *.gouv.ga / *.ga + CDX PDF / JO)",
        notes=(
            "Official *.ga / *.gouv.ga JO/SGG/justice/primature/présidence PDFs only (Gabon). "
            "OCR fra for scans. Not AfricanLII. No WAF bypass. Not legal advice. "
            "ga=Gabon (not Congo-Brazzaville/cg, not DRC/cd, not Equatorial Guinea)."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s total_instruments=%s", ok, skip, fail, len(done))


if __name__ == "__main__":
    main()
