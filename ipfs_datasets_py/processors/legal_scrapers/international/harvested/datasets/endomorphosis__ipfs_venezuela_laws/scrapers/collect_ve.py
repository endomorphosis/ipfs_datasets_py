#!/usr/bin/env python3
"""Venezuela: Gaceta Oficial / Imprenta Nacional PDFs (live + Wayback of official hosts).

Official hosts only:
  http://www.gacetaoficial.gob.ve/
  http://www.imprentanacional.gob.ve/
No vLex / La Ley / commercial aggregators. HTTPS Wayback CDX is SSL-flaky from
this host — discovery uses HTTP CDX. Many gazette PDFs are image scans → OCR (spa).
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))

import json
import logging
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from urllib.parse import unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, base_record, existing_ids, log_failure, slug_id, utcnow, write_instrument, write_summary
from world_lib import env_int, setup_log
import archive_fallbacks as af
from pdf_extract_lib import extract_pdf_text, honest_split

CC, COUNTRY, LANG = "ve", "Venezuela", "es"
SOURCE_TYPE = "gaceta_oficial_ve"
LICENSE = (
    "Gaceta Oficial de la República Bolivariana de Venezuela "
    "(gacetaoficial.gob.ve / Imprenta Nacional). "
    "Authentic gazette text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=http://www.gacetaoficial.gob.ve/)"
ART = re.compile(r"(?im)^\s*((?:Art(?:[íi]culo|\.|iculo)?|ART[IÍ]CULO)\s+[\d]+[º°o.]?)\b")
log = logging.getLogger("ve")

OFFICIAL_HOSTS = (
    "gacetaoficial.gob.ve",
    "imprentanacional.gob.ve",
)
# Prefer Spanish OCR; TESSDATA_PREFIX should include spa.traineddata
os.environ.setdefault("TESSDATA_PREFIX", "/home/box/tessdata")

def is_thin_es(text: str) -> bool:
    """Reject empty/PDF-binary/OCR-noise; do NOT use Arabic-mojibake heuristics on Spanish."""
    if not text or len(text) < 120:
        return True
    if text.lstrip().startswith("%PDF") or "endobj" in text[:200]:
        return True
    sample = text[:8000]
    letters = sum(ch.isalpha() for ch in sample)
    if letters < 200:
        return True
    # spaced-out OCR garbage
    if sample.count(" ") > letters * 2.2:
        return True
    singles = len(__import__("re").findall(r"(?m)^\s*[A-Za-zÁÉÍÓÚÑáéíóúñ]\s*$", sample))
    if singles > 40 and singles > letters * 0.2:
        return True
    # require some gazette/law vocabulary when possible, else accept letter-rich text
    low = sample.lower()
    if letters >= 400:
        return False
    return not any(k in low for k in ("gaceta", "artículo", "articulo", "decreto", "ley ", "resoluci", "república", "republica"))



def _norm_url(url: str) -> str:
    url = (url or "").strip().split("#")[0]
    url = url.replace("https://", "http://")
    url = re.sub(r":80/", "/", url)
    # bare host without scheme sometimes appears in CDX
    if url.startswith("//"):
        url = "http:" + url
    if not url.startswith("http"):
        url = "http://" + url.lstrip("/")
    # prefer www for live DNS
    url = url.replace("http://gacetaoficial.gob.ve/", "http://www.gacetaoficial.gob.ve/")
    url = url.replace("http://imprentanacional.gob.ve/", "http://www.imprentanacional.gob.ve/")
    return url


def _is_official_pdf(url: str) -> bool:
    low = url.lower()
    if ".pdf" not in low:
        return False
    if not any(h in low for h in OFFICIAL_HOSTS):
        return False
    # skip marketing / certificates / catalogs
    if any(x in low for x in (
        "/catalogos/", "certificado_gaceta", "/firmados/certificado_",
        "contrato.pdf", "normas.pdf", "catalogo.pdf",
    )):
        return False
    return True


def http_cdx(prefix: str, *, limit: int = 40) -> list[dict]:
    """HTTP Wayback CDX (HTTPS often SSLEOF from this host)."""
    parts = [
        f"url={urllib.parse.quote(prefix)}",
        "output=json",
        "fl=original,timestamp,mimetype,statuscode,length",
        f"limit={limit}",
        "collapse=urlkey",
        "matchType=prefix",
        "filter=" + urllib.parse.quote("statuscode:200"),
        "filter=" + urllib.parse.quote("mimetype:application/pdf"),
    ]
    api = "http://web.archive.org/cdx/search/cdx?" + "&".join(parts)
    try:
        req = urllib.request.Request(api, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as exc:
        log.info("cdx fail %s: %s", prefix, exc)
        return []
    if not data:
        return []
    rows = data[1:] if data[0] and data[0][0] == "original" else data
    out = []
    for row in rows:
        if len(row) < 2:
            continue
        out.append({
            "original": row[0],
            "timestamp": row[1],
            "mimetype": row[2] if len(row) > 2 else "",
            "statuscode": row[3] if len(row) > 3 else "",
            "length": row[4] if len(row) > 4 else "0",
        })
    return out


def discover() -> list[tuple[str, str, str | None, int]]:
    """Return (ident, url, wayback_ts, length) sorted for quality-first harvest.

    Densify wave: higher CDX limits across storage years + Imprenta + Asamblea leyes.
    Prefer EXTRAORDINARIA / ley / codigo / constitucion over noise.
    """
    items: list[tuple[str, str, str | None, int]] = []
    seen: set[str] = set()

    def add(url: str, ts: str | None = None, length: int = 0):
        url = _norm_url(url)
        if not _is_official_pdf(url):
            return
        key = url.lower().replace("http://www.", "http://")
        if key in seen:
            return
        seen.add(key)
        path = unquote(urlparse(url).path)
        stem = Path(path).stem[:160] or re.sub(r"\W+", "-", url)[-80:]
        ident = re.sub(r"[^a-zA-Z0-9._-]+", "_", stem).strip("_")[:140] or "gaceta"
        items.append((ident, url, ts, length))

    def add_host_pdf(url: str, ts: str | None = None, length: int = 0, hosts=OFFICIAL_HOSTS):
        """Allow Asamblea / TSJ official PDFs when hosts expanded."""
        url = _norm_url(url)
        low = url.lower()
        if ".pdf" not in low:
            return
        if not any(h in low for h in hosts):
            return
        if any(x in low for x in (
            "/catalogos/", "certificado_gaceta", "/firmados/certificado_",
            "contrato.pdf", "catalogo.pdf", "acuerdo%", "acuerdo ",
        )):
            # keep leyes; skip acuerdos/certificates later via rank
            pass
        key = url.lower().replace("http://www.", "http://")
        if key in seen:
            return
        seen.add(key)
        path = unquote(urlparse(url).path)
        stem = Path(path).stem[:160] or re.sub(r"\W+", "-", url)[-80:]
        ident = re.sub(r"[^a-zA-Z0-9._-]+", "_", stem).strip("_")[:140] or "doc"
        items.append((ident, url, ts, length))

    # Seeds (live path patterns)
    for seed in (
        "http://www.gacetaoficial.gob.ve/storage/2020/T028700032188-0-41.800_15-01-2020-000.pdf",
    ):
        add(seed, None, 0)

    cdx_limit = env_int("CDX_LIMIT", 2000)
    per_year = env_int("CDX_PER_YEAR", max(80, min(400, cdx_limit // 8)))
    sleep_s = float(os.environ.get("CDX_SLEEP", "1.2"))

    # Broad year-scoped storage CDX
    years = list(range(2012, 2026))
    for year in years:
        for host in ("gacetaoficial.gob.ve",):  # www duplicates; collapse=urlkey still helps
            rows = http_cdx(f"{host}/storage/{year}/", limit=per_year)
            if not rows and sleep_s:
                time.sleep(sleep_s)
                rows = http_cdx(f"www.{host}/storage/{year}/" if not host.startswith("www.") else f"{host}/storage/{year}/", limit=per_year)
            for h in rows:
                try:
                    length = int(h.get("length") or 0)
                except Exception:
                    length = 0
                add(h.get("original") or "", h.get("timestamp"), length)
            if sleep_s:
                time.sleep(sleep_s)

    # Extra pass for EXTRAORDINARIA filename patterns (quality)
    for prefix in (
        "gacetaoficial.gob.ve/storage/*EXTRAORDINARIA*",
        "gacetaoficial.gob.ve/storage/*Extraordinaria*",
        "gacetaoficial.gob.ve/storage/*extra*",
    ):
        # CDX matchType=prefix does not do glob; use year EXTRA folders already covered
        pass

    # Imprenta Nacional historical gaceta PDFs (official host)
    for h in http_cdx(
        "www.imprentanacional.gob.ve/gaceta_imprenta/usuarios/administrador/gacetas/",
        limit=env_int("CDX_IMPRENTA", min(400, cdx_limit // 4)),
    ):
        try:
            length = int(h.get("length") or 0)
        except Exception:
            length = 0
        add(h.get("original") or "", h.get("timestamp"), length)
    if sleep_s:
        time.sleep(sleep_s)

    # Asamblea Nacional — prefer leyes / códigos / constitución PDFs (official)
    an_hosts = ("asambleanacional.gob.ve", "www.asambleanacional.gob.ve")
    for prefix in (
        "www.asambleanacional.gob.ve/documentos_leyes/",
        "asambleanacional.gob.ve/documentos_leyes/",
        "www.asambleanacional.gob.ve/documentos_archivos/",
        "asambleanacional.gob.ve/documentos_archivos/",
        "www.asambleanacional.gob.ve/contenido/",
        "asambleanacional.gob.ve/contenido/",
        "www.asambleanacional.gob.ve/documentos/",
        "asambleanacional.gob.ve/documentos/",
    ):
        for h in http_cdx(prefix, limit=env_int("CDX_AN", min(250, cdx_limit // 6))):
            orig = h.get("original") or ""
            low = orig.lower()
            if not any(k in low for k in (
                "ley", "codigo", "c%c3%b3digo", "constituci", "organica",
                "org%c3%a1nica", "reforma", "codigo_penal", "codigo_civil",
                "documentos_leyes",
            )):
                continue
            if any(k in low for k in (
                "acuerdo", "comunicado", "carta", "invitacion", "invitación",
                "proyecto-de-ley", "proyecto_de_ley", "informe-sobre", "cronograma",
                "estatuto-que-rige", "transicion-a-la-democracia", "transici%c3%b3n",
            )):
                continue
            try:
                length = int(h.get("length") or 0)
            except Exception:
                length = 0
            add_host_pdf(orig, h.get("timestamp"), length, hosts=an_hosts + OFFICIAL_HOSTS)
        if sleep_s:
            time.sleep(sleep_s)

    # TSJ documents that look like leyes/códigos (not decisions catalogs)
    tsj_hosts = ("tsj.gob.ve", "www.tsj.gob.ve")
    for prefix in (
        "www.tsj.gob.ve/documents/",
        "tsj.gob.ve/documents/",
    ):
        for h in http_cdx(prefix, limit=env_int("CDX_TSJ", min(150, cdx_limit // 10))):
            orig = h.get("original") or ""
            low = urllib.parse.unquote(orig).lower()
            if not any(k in low for k in ("ley", "codigo", "código", "constituci", "organica", "orgánica")):
                continue
            if "decision" in low or "sentencia" in low:
                continue
            try:
                length = int(h.get("length") or 0)
            except Exception:
                length = 0
            add_host_pdf(orig, h.get("timestamp"), length, hosts=tsj_hosts + OFFICIAL_HOSTS)
        if sleep_s:
            time.sleep(sleep_s)

    def rank(it):
        ident, url, ts, length = it
        low = urllib.parse.unquote(url).lower()
        # Volume-first densify: live Gaceta Oficial PDFs, then Constitution/AN leyes,
        # then Imprenta. Demote proyectos/informes.
        name = Path(urllib.parse.unquote(urlparse(url).path)).name.lower()
        if any(k in low for k in (
            "proyecto", "informe-sobre", "comunicado", "acuerdo",
            "estatuto-que-rige", "transicion-a-la-democracia",
        )):
            bucket = 9
        elif ("constitucion-nacional" in name or name.startswith("constituci")) and "estatuto" not in low:
            bucket = 0
        elif "gacetaoficial.gob.ve" in low and "extra" in low:
            bucket = 1
        elif "gacetaoficial.gob.ve" in low:
            bucket = 2
        elif any(k in low for k in ("codigo", "código", "organica", "orgánica", "ley-organica", "ley_organica")):
            bucket = 3
        elif "documentos_leyes" in low or "ley" in low:
            bucket = 4
        elif "imprentanacional" in low:
            bucket = 5
        else:
            bucket = 6
        huge = 0 if length == 0 or length <= 4_000_000 else (1 if length <= 8_000_000 else 2)
        size = length if length > 0 else 9_999_999
        host_rank = 0 if "gacetaoficial.gob.ve" in low else (1 if "asambleanacional" in low else (2 if "imprentanacional" in low else 3))
        return (bucket, huge, host_rank, size, ident)

    # Keep official gazette + curated AN/TSJ leyes; drop noise hosts
    allowed = OFFICIAL_HOSTS + ("asambleanacional.gob.ve", "tsj.gob.ve")
    items = [it for it in items if any(h in it[1].lower() for h in allowed)]

    items.sort(key=rank)
    # Cap catalog to CDX_LIMIT unique URLs for harvest pacing
    if len(items) > cdx_limit:
        items = items[:cdx_limit]
    log.info("catalog %s", len(items))
    return items


def fetch_pdf(url: str, ts: str | None = None) -> tuple[bytes, str]:
    """Live official PDF first; HTTP Wayback id_ replay on failure (HTTPS CDX/replay SSL-flaky)."""
    import requests
    requests.packages.urllib3.disable_warnings()  # type: ignore

    def get_bytes(u: str, timeout=(12, 90)) -> bytes:
        r = requests.get(u, timeout=timeout, verify=False, headers={"User-Agent": UA})
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            return r.content
        return b""

    # Try live URL; https only for AN/TSJ (gacetaoficial is http-live)
    live_urls = [url]
    lowu = url.lower()
    if url.startswith("http://") and any(h in lowu for h in ("asambleanacional.gob.ve", "tsj.gob.ve")):
        live_urls.append("https://" + url[len("http://"):])
    for lu in live_urls:
        try:
            body = get_bytes(lu, timeout=(10, 60) if "gacetaoficial" in lu.lower() else (8, 35))
            if body:
                return body, "http_pdf"
        except Exception as exc:
            log.debug("live %s: %s", lu[:80], exc)

    # Prefer HTTP Wayback replay (HTTPS often SSLEOF from this host)
    candidates = []
    if ts:
        candidates.append(f"http://web.archive.org/web/{ts}id_/{url}")
    candidates.append(f"http://web.archive.org/web/2id_/{url}")
    for wu in candidates:
        try:
            body = get_bytes(wu, timeout=(15, 100))
            if body:
                return body, "wayback_pdf"
        except Exception as exc:
            log.debug("wb %s: %s", wu[:90], exc)
    # Last resort: existing archive_fallbacks (may HTTPS-fail)
    try:
        w = af.get_wayback_content(url, timestamp=ts)
        body = w.get("content") or b""
        if w.get("status") == "success" and isinstance(body, bytes) and body[:4] == b"%PDF":
            return body, "wayback_pdf"
    except Exception:
        pass
    return b"", "fail"



def first_title(text: str, fallback: str) -> str:
    for line in (text or "").splitlines():
        s = line.strip()
        if len(s) >= 12 and not s.lower().startswith("just a moment"):
            # skip OCR junk headers that are too short/noisy
            if re.search(r"(?i)gaceta\s+oficial|rep[uú]blica|constituci|ley |decreto|resoluci", s):
                return s[:240]
            if len(s) > 24:
                return s[:240]
    return fallback[:240]


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 35)
    max_seconds = env_int("MAX_SECONDS", 2700)
    ocr_pages = env_int("OCR_PAGES", 10)
    max_bytes = env_int("MAX_PDF_BYTES", 8_000_000)
    t_start = time.time()
    done = existing_ids(CC)
    ok = skip = fail = ocr_used = 0

    for ident, url, ts, length in discover():
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        if length and length > max_bytes:
            skip += 1
            continue
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        raw, method = fetch_pdf(url, ts)
        if not raw:
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "fetch_fail"})
            continue
        if len(raw) > max_bytes * 1.2:
            skip += 1
            continue
        text, how, pages = extract_pdf_text(
            raw, enable_ocr=True, ocr_lang="spa", ocr_max_pages=ocr_pages,
        )
        if how.startswith("ocr"):
            ocr_used += 1
        if not text or len(text) < 120 or is_thin_es(text):
            fail += 1
            log_failure(CC, {
                "identifier": ident, "source_url": url,
                "reason": f"thin:{how}", "chars": len(text or ""),
            })
            continue
        docs, kind = honest_split(CC, text, rid, url)
        # Prefer Spanish Artículo regex when honest_split yields few docs
        if len(docs) < 2:
            matches = list(ART.finditer(text))
            if len(matches) >= 2:
                docs = []
                for i, m in enumerate(matches):
                    start = m.start()
                    end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
                    chunk = text[start:end].strip()
                    if len(chunk) < 20:
                        continue
                    num = re.sub(r"\s+", " ", m.group(1)).strip()
                    aid = re.sub(r"[^a-zA-Z0-9-]+", "-", num.lower()).strip("-")[:80]
                    docs.append({
                        "id": f"{rid}-{aid}"[:180],
                        "title": chunk.split("\n", 1)[0][:200],
                        "text": chunk,
                        "date_filed": None,
                        "document_number": num,
                        "source_url": url,
                        "record_type": "article",
                        "article_number": num,
                        "law_identifier": ident,
                        "metadata": {"text_extraction": {"source": "ocr_or_pdf", "backend": how}},
                    })
                kind = "articulo_re"

        title = first_title(text, ident)
        # date from filename patterns YYYY-MM-DD or DD-MM-YYYY
        date = None
        m = re.search(r"(20\d{2})-(\d{2})-(\d{2})", ident)
        if m:
            date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        else:
            m = re.search(r"(\d{2})-(\d{2})-(20\d{2})", ident)
            if m:
                date = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"

        rec = base_record(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_ve.py",
            date=date, documents=docs,
            extra_meta={
                "fetch_method": method,
                "extract_method": how,
                "pages": pages,
                "pdf_bytes": len(raw),
                "article_split": {"method": kind, "count": len(docs)},
                "wayback_ts": ts,
                "official_hosts": list(OFFICIAL_HOSTS),
            },
        )
        write_instrument(CC, rec)
        ok += 1
        done.add(rid)
        log.info("ok %s method=%s extract=%s arts=%s chars=%s", ident[:70], method, how, len(docs), len(text))

    write_summary(
        CC, country=COUNTRY,
        source="Gaceta Oficial / Imprenta Nacional (Venezuela)",
        source_urls=[
            "http://www.gacetaoficial.gob.ve/",
            "http://www.imprentanacional.gob.ve/",
        ],
        license_text=LICENSE,
        discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (live + Wayback of official Gaceta PDFs; OCR on scans)",
        notes=(
            f"OCR(spa) used on {ocr_used} image-heavy gazettes when text layer missing. "
            "Constitution 1999 (G.O. Ext. 36.860) not located as PDF on these official hosts in CDX. "
            "Not vLex/La Ley. Not legal advice."
        ),
        last_run=t0,
    )
    laws = arts = 0
    for p in (ROOT / CC / "instruments").glob("*.json"):
        rec = json.loads(p.read_text(encoding="utf-8"))
        if len(rec.get("text") or "") >= 80:
            laws += 1
            arts += len(rec.get("documents") or [])
    print(json.dumps({
        "ok": ok, "skip": skip, "fail": fail, "ocr_used": ocr_used,
        "laws": laws, "arts": arts,
    }))


if __name__ == "__main__":
    main()
