#!/usr/bin/env python3
"""Central African Republic / RCA / CAR (cf): official law / JO PDFs from *.cf / *.gouv.cf / *.gov.cf.

Official only:
  - https://www.gouv.cf/ / gouv.cf (portail)
  - SGG / Journal Officiel / Primature / Justice / Finances / Mines / Présidence / AN
  - Wayback/CDX of the same official *.cf / *.gouv.cf / *.gov.cf URLs

Filter: prefer loi/ordonnance/décret/constitution/code/JO; skip PDFs >12MB.
Not AfricanLII / Droit-Afrique. No WAF bypass. Not legal advice.
NOTE: country code cf = Central African Republic / RCA (not Chad td, not DRC cd).
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

CC, COUNTRY, LANG = "cf", "Central African Republic", "fr"
SOURCE_TYPE = "jo_car_official"
LICENSE = (
    "République Centrafricaine / RCA — Portail du Gouvernement (gouv.cf) / "
    "SGG / Journal Officiel / Primature / Justice / Finances / Mines / "
    "Présidence / Assemblée nationale (*.cf / *.gouv.cf / *.gov.cf). "
    "Authentic Journal Officiel / official text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.gouv.cf/; CAR/RCA=cf not td/cd)"
ART = re.compile(r"(?im)^\s*((?:Article|Art\.?)\s+\d+[a-zA-Zº°]?)\b")
log = logging.getLogger("cf")

MAX_PDF_BYTES = 12 * 1024 * 1024

ALLOWED = (
    "gouv.cf",
    "www.gouv.cf",
    "gov.cf",
    "www.gov.cf",
    "sgg.gouv.cf",
    "www.sgg.gouv.cf",
    "sgg.cf",
    "journalofficiel.gouv.cf",
    "www.journalofficiel.gouv.cf",
    "journalofficiel.cf",
    "jo.gouv.cf",
    "www.jo.gouv.cf",
    "justice.gouv.cf",
    "www.justice.gouv.cf",
    "justice.cf",
    "primature.gouv.cf",
    "www.primature.gouv.cf",
    "primature.cf",
    "finances.gouv.cf",
    "www.finances.gouv.cf",
    "minefi.gouv.cf",
    "www.minefi.gouv.cf",
    "mines.gouv.cf",
    "www.mines.gouv.cf",
    "presidence.cf",
    "www.presidence.cf",
    "presidence.gouv.cf",
    "www.presidence.gouv.cf",
    "assemblee-nationale.cf",
    "www.assemblee-nationale.cf",
    "assembleenationale.cf",
    "www.assembleenationale.cf",
    "an.cf",
    "www.an.cf",
    "an.gouv.cf",
    "hautconseil.cf",
    "cnt.cf",
    "anr.cf",
    "www.anr.cf",
    "centrafrique.gouv.cf",
    "rca.gouv.cf",
    "www.rca.gouv.cf",
)

KEEP_RE = re.compile(
    r"(loi|ordonnance|ordonn|d[eé]cret|decret|arr[eê]t[eé]|arrete|constitution|code|"
    r"journal.?officiel|\bjos?\b|\bjo\b|organique|r[eè]glement|charte|statut|"
    r"circulaire|cgi\b|nbe\b|pce\b|tofe\b|rgcp\b|ccag\b|manuel|"
    r"wp-content/uploads|/uploads/|/documents?/|/jo/|textes?|"
    r"centrafricaine|rca\b)",
    re.I,
)
DROP_RE = re.compile(
    r"(africanlii|centraflii|droit-afrique|gazettes\.africa|law\.africa|"
    r"discours|allocution|communique|photo|banner|logo|cv[-_]|"
    r"biographie|rapport[-_ ]annuel|presentation|organigramme|"
    r"newsletter|recrutement|facebook|twitter|linkedin|"
    r"album|actualites|appel.?d.?offres|"
    r"\bppm\b|\baaoo\b|\baaor\b|\bami\b|avis.?d.?appel|plan.?previsionnel|"
    r"structure[-_ ]?(des[-_ ]?)?prix|stations?-services?|"
    r"reporting|bulletin.?stat|reb[-_ ]|execution.?budgetaire|"
    r"opinion.?sur.?les.?comptes|controle.?interne|"
    r"contribuables|exon[eé]rations|tdr[s]?\b|avis.?a.?manifestation)",
    re.I,
)
TEXT_KEEP_RE = re.compile(
    r"\b(loi|ordonnance|d[eé]cret|decret|constitution|journal\s+officiel|"
    r"code|r[eé]publique\s+centrafricaine|assembl[eé]e\s+nationale|"
    r"pr[eé]sident\s+de\s+la\s+r[eé]publique|promulgue|partie\s+officielle|"
    r"conseil\s+des\s+ministres|centrafrique|\brca\b)\b",
    re.I,
)

SEED_PDFS = [
    # Deepen pass: official finances/justice under-12MB (live listing)
    "https://www.finances.gouv.cf/sites/default/files/2025-11/Loi_De_Reglement_2018.pdf",
    "https://www.finances.gouv.cf/sites/default/files/2025-11/Loi_De_Reglement_2019.pdf",
    "https://www.finances.gouv.cf/sites/default/files/2024-12/TEXTE%20DE%20LOI%202025.pdf",
    "https://www.finances.gouv.cf/sites/default/files/2025-03/Loi%2025.04%20Budget%20de%20l'Excercie%202017.pdf",
    "https://www.finances.gouv.cf/sites/default/files/2025-03/Loi%2025.05%20Budget%20de%20l'Excercie%202016.pdf",
    "https://www.finances.gouv.cf/sites/default/files/2023-05/CGI%20RCA%202017%20mise%20%C3%A0%20jour%202023.pdf",
    "https://www.finances.gouv.cf/sites/default/files/2021-02/09.044%20CCAG.pdf",
    "https://www.finances.gouv.cf/sites/default/files/2021-02/09.113%20mod%20exe%20conv.pdf",
    "https://www.finances.gouv.cf/sites/default/files/2021-02/09.114%20seuils%20approbation.pdf",
    "https://www.finances.gouv.cf/sites/default/files/2021-03/Circulaire%20DGMP.pdf",
    "https://www.finances.gouv.cf/sites/default/files/2021-03/Circulaire%20Mise%20en%20oeuvre%20de%20la%20procedure%20de%20passation%20des%20march%C3%A9s.pdf",
    "https://www.finances.gouv.cf/sites/default/files/2021-03/Note%20circulaire%20ex%C3%A9cution%20budget.pdf",
    "https://finances.gouv.cf/sites/default/files/2023-11/ARRETE%20PROGRAMME%20ET%20DOTATION_compressed.pdf",
    "https://finances.gouv.cf/sites/default/files/2025-11/Arr%C3%A9t%C3%A9%20d'approbation%20du%20manuel%20de%20procedure%20de%20la%20dette_0.pdf",
    "https://finances.gouv.cf/sites/default/files/2025-11/Arr%C3%A9t%C3%A9%20du%20Comit%C3%A9%20de%20Tr%C3%A9sorerie.pdf",
    "https://finances.gouv.cf/sites/default/files/2025-11/RCA%20MANUEL%20DE%20PROCEDURE%20DE%20GESTION%20DE%20LA%20DETTE%20pdf.pdf",
    "https://www.finances.gouv.cf/sites/default/files/2021-02/manuel%20de%20proc%C3%A9dure%20version%20finale%20%20approuv%C3%A9e.pdf",
    "https://www.finances.gouv.cf/sites/default/files/2024-05/Arr%C3%AAt%C3%A9%20n%C2%B0%20020,%20fixant%20les%20prix%20des%20produits%20p%C3%A9troliers%20pour%20le%20mois%20de%20mai%202024.pdf",
    "https://www.justice.gouv.cf/sites/default/files/2022-02/CODE%20DE%20LA%20FAMILLE.pdf",
    "https://www.justice.gouv.cf/sites/default/files/2022-02/Loi%20Statut%20juges%20administratifs.pdf",
    "https://finances.gouv.cf/sites/default/files/2021-03/3.%20NBE.pdf",
    "https://finances.gouv.cf/sites/default/files/2021-03/4.%20PCE.pdf",
    "https://www.finances.gouv.cf/sites/default/files/2021-03/6.%20TOFE.pdf",
    "https://www.finances.gouv.cf/sites/default/files/2021-02/REFERENTIEL%20DE%20PRIX%20POUR%20LA%20COMMANDE%20PUBLIQUE.pdf",
    "https://finances.gouv.cf/sites/default/files/2021-06/CIRCULAIRE%20PORTANT%20INSTRUCTIONS%20RELATIVES%20A%20L'EXECUTION%20DU%20BDUEGT%20DE%20L'ETAT_Gestion%202021.pdf",
    "https://justice.gouv.cf/sites/default/files/2022-02/CODE%20DE%20LA%20FAMILLE.pdf",
    "https://justice.gouv.cf/sites/default/files/2022-02/Loi%20Statut%20juges%20administratifs.pdf",
    "https://www.finances.gouv.cf/sites/default/files/2025-07/Scan_Arrete_Prix_Prod_Petrol_Juillet-2025.pdf",
    "https://www.finances.gouv.cf/sites/default/files/2025-12/Arr%C3%AAt%C3%A9-structure_PPP-d%C3%A9c.%202025.pdf",
]

HOMES = [
    "https://www.gouv.cf/",
    "https://gouv.cf/",
    "https://sgg.gouv.cf/",
    "https://www.sgg.gouv.cf/",
    "https://journalofficiel.gouv.cf/",
    "https://jo.gouv.cf/",
    "https://justice.gouv.cf/",
    "https://www.justice.gouv.cf/",
    "https://justice.gouv.cf/publications",
    "https://primature.gouv.cf/",
    "https://finances.gouv.cf/",
    "https://www.finances.gouv.cf/",
    "https://www.finances.gouv.cf/documentations",
    "https://www.finances.gouv.cf/index.php/finances/les-lois-de-finances-ldf",
    "https://www.finances.gouv.cf/index.php/finances/decrets-et-arretes",
    "https://www.finances.gouv.cf/index.php/marches-publics/textes-reglementaires",
    "https://finances.gouv.cf/documentations",
    "https://finances.gouv.cf/index.php/finances/les-lois-de-finances-ldf",
    "https://finances.gouv.cf/index.php/finances/decrets-et-arretes",
    "https://finances.gouv.cf/index.php/marches-publics/textes-reglementaires",
    "https://mines.gouv.cf/",
    "https://presidence.cf/",
    "https://www.presidence.cf/",
    "https://presidence.gouv.cf/",
    "https://assemblee-nationale.cf/",
    "https://www.assemblee-nationale.cf/",
    "https://an.cf/",
]

CDX_PREFIXES = (
    "gouv.cf/",
    "www.gouv.cf/",
    "sgg.gouv.cf/",
    "www.sgg.gouv.cf/",
    "journalofficiel.gouv.cf/",
    "jo.gouv.cf/",
    "justice.gouv.cf/",
    "www.justice.gouv.cf/",
    "primature.gouv.cf/",
    "finances.gouv.cf/",
    "www.finances.gouv.cf/",
    "minefi.gouv.cf/",
    "mines.gouv.cf/",
    "www.mines.gouv.cf/",
    "presidence.cf/",
    "www.presidence.cf/",
    "presidence.gouv.cf/",
    "assemblee-nationale.cf/",
    "www.assemblee-nationale.cf/",
    "assembleenationale.cf/",
    "an.cf/",
    "an.gouv.cf/",
    "hautconseil.cf/",
    "cnt.cf/",
    "anr.cf/",
)


def _host_ok(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    if any(x in host for x in ("africanlii", "centraflii", "droit-afrique", "gazettes.africa", "law.africa")):
        return False
    # Never harvest Chad or DRC hosts from this collector
    if host.endswith(".td") or host.endswith(".cd") or "congo" in host:
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
        if host.startswith("www.") and host[4:] in ALLOWED:
            # keep www when both allowed; normalize only duplicates later via seen key
            pass
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
        or "/jo/" in path
        or "journal-officiel" in path
        or re.search(r"(?i)(jo[-_]?\d|journal.?officiel)", path)
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


def fetch_cf(url: str, wayback_ts: str | None = None) -> dict:
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
    max_ocr_bytes = env_int("MAX_OCR_BYTES", 12 * 1024 * 1024)
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


def _stem_key(url: str) -> str:
    name = unquote(urlsplit(url).path).split("/")[-1].lower()
    name = re.sub(r"_[0-9]+(?=\.pdf$)", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name

def _add(items, seen, ident, url, ts=None, priority=50, size_hint=None, title=None):
    url = _norm_url(url)
    if not url or not _keep(url, title=title):
        return
    key = url.lower().split("?")[0]
    # collapse www. duplicate
    key2 = key.replace("://www.", "://")
    stem = _stem_key(url)
    if key in seen or key2 in seen or (stem and stem in seen):
        return
    if size_hint and size_hint > MAX_PDF_BYTES:
        return
    seen.add(key)
    seen.add(key2)
    if stem:
        seen.add(stem)
    ident = re.sub(r"\W+", "-", (ident or _ident_from_url(url, title)).strip("-")).lower()[:160]
    items.append((priority, ident, url, ts, size_hint, title))


def discover():
    items = []
    seen = set()
    # avoid re-adding stems already on disk
    try:
        from common import existing_ids as _eid  # noqa: F401
        import json as _json
        idx = Path(__file__).resolve().parents[1] / "cf" / "index.jsonl"
        if idx.exists():
            for line in idx.read_text().splitlines():
                if not line.strip():
                    continue
                rec = _json.loads(line)
                u = rec.get("source_url") or ""
                if u:
                    seen.add(u.lower().split("?")[0])
                    seen.add(u.lower().split("?")[0].replace("://www.", "://"))
                    sk = _stem_key(u)
                    if sk:
                        seen.add(sk)
    except Exception as exc:
        log.info("existing stem load: %s", exc)

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
            log.info("home %s links=%s", home, n)
        except Exception as exc:
            log.info("home %s %s", home, exc)

    for prefix in CDX_PREFIXES:
        try:
            hits = cdx_urls(
                prefix,
                limit=env_int("CDX_LIMIT", 600),
                match_type="prefix",
                extra_filters=["statuscode:200", "mimetype:application/pdf"],
            ) or []
        except Exception as exc:
            log.info("cdx %s %s", prefix, exc)
            hits = []
        # also try without mimetype filter (some JO served as octet-stream)
        if len(hits) < 5:
            try:
                hits2 = cdx_urls(
                    prefix,
                    limit=env_int("CDX_LIMIT", 600),
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
    max_new = env_int("MAX_NEW", 45)
    max_seconds = env_int("MAX_SECONDS", 2400)
    t_start = time.time()
    done = existing_ids(CC)
    already = len(done)
    target_total = env_int("TARGET_TOTAL", 80)
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
        got = fetch_cf(url, wayback_ts=ts)
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
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_cf.py",
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
        source="Central African Republic / RCA (gouv.cf / SGG / JO / Primature / Justice / Finances / Présidence / AN)",
        source_urls=[
            "https://www.gouv.cf/",
            "https://sgg.gouv.cf/",
            "https://journalofficiel.gouv.cf/",
            "https://justice.gouv.cf/",
            "https://primature.gouv.cf/",
            "https://finances.gouv.cf/",
            "https://presidence.cf/",
            "https://assemblee-nationale.cf/",
        ],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (live crawl *.gouv.cf / *.cf + CDX PDF / JO)",
        notes="Official *.cf / *.gouv.cf / *.gov.cf JO/SGG/justice/primature PDFs only. OCR fra for scans. Not AfricanLII. No WAF bypass. Not legal advice. cf=CAR/RCA (not td/cd).",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s total_instruments=%s", ok, skip, fail, len(done))


if __name__ == "__main__":
    main()
