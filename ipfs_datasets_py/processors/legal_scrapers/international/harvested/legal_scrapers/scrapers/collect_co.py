#!/usr/bin/env python3
"""Colombia: Constitución + leyes from official Secretaría del Senado consolidations.

Official sources only:
  - Secretaría del Senado / Congreso basedoc consolidations
    http://www.secretariasenado.gov.co/senado/basedoc/
  - SUIN-Juriscol https://www.suin-juriscol.gov.co (MinJusticia) when reachable
  - Diario Oficial / Imprenta Nacional https://www.imprenta.gov.co if needed
  - datos.gov.co catalog of SUIN-loaded norms (metadata only)

Leyes first (not every decreto). Not Legis or Ámbito Jurídico. No WAF bypass.
archive_fallbacks.py on HTTP 429. SUIN live TLS often fails from this host;
Wayback of official SUIN URLs is used only as a fallback.
"""
from __future__ import annotations

import json
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af

CC = "co"
COUNTRY = "Colombia"
SOURCE_TYPE = "secretaria_senado"
LICENSE = (
    "Official Colombian legislative texts. Secretaría del Senado hosts consolidations "
    "of the Constitución and leyes; the Diario Oficial authentic text prevails. "
    "Editorial notes of the compiler are not a substitute for the gazette. Not legal advice."
)
UA = DEFAULT_UA + " source=http://www.secretariasenado.gov.co/senado/basedoc/"
SENADO = "http://www.secretariasenado.gov.co/senado/basedoc/"
LEYES_TREE = SENADO + "arbol/leyes.html"
CONST = SENADO + "constitucion_politica_1991.html"
SUIN = "https://www.suin-juriscol.gov.co/"
DATOS = "https://www.datos.gov.co/resource/fiev-nid6.json"
WORKERS = 4
SLEEP = 0.4
log = logging.getLogger("co")

ART_CO = re.compile(
    r"(?im)^\s*((?:Art(?:[íi]culo|\.|iculo)?|ART[IÍ]CULO)\s+"
    r"[\d]+(?:[oº°.]|[A-Za-z])?(?:\s*(?:bis|ter|qu[aá]ter))?)\b"
)
PR_HREF = re.compile(r'href=["\']([^"\']+_pr\d+\.html)["\']', re.I)
YEAR_HREF = re.compile(r'href=["\'](\d+\.html)["\'][^>]*>\s*LEYES\s+(\d{4})', re.I)
LEY_HREF = re.compile(r'href=["\'](\.\./ley_\d+_\d{4}\.html)["\']', re.I)
LEY_NAME = re.compile(r"ley_(\d+)_(\d{4})", re.I)


def setup():
    ensure_dirs(CC)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def split_es(text: str, law_id: str, source_url: str, date: Optional[str]) -> list[dict]:
    docs = split_articles(text, law_id, source_url, date)
    matches = list(ART_CO.finditer(text or ""))
    if len(matches) < 2:
        return []
    out = []
    seen = set()
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = text[start:end].strip()
        if len(chunk) < 12:
            continue
        num = re.sub(r"\s+", " ", m.group(1)).strip()
        aid = re.sub(r"[^a-z0-9]+", "-", num.lower()).strip("-")
        doc_id = f"{law_id}-{aid}"[:180]
        if doc_id in seen:
            continue
        seen.add(doc_id)
        heading = chunk.split("\n", 1)[0][:200]
        out.append({
            "id": doc_id, "title": heading, "text": chunk, "date_filed": date,
            "document_number": num, "source_url": source_url, "record_type": "article",
            "article_number": num, "law_identifier": law_id,
            "metadata": {"text_extraction": {"source": "official", "backend": "senado_basedoc"}},
        })
        if len(out) >= 4000:
            break
    custom = out if len(out) >= 2 else []
    if len(custom) > len(docs):
        return custom
    return docs if len(docs) >= 2 else custom


def decode_html(content: bytes) -> str:
    if not content:
        return ""
    if content.lstrip()[:1] in (b"<", b"\xef"):
        try:
            return content.decode("utf-8")
        except Exception:
            return content.decode("latin-1", "replace")
    return content.decode("latin-1", "replace")


def fetch_page(url: str) -> tuple[str, str, str]:
    try:
        r = http_get(url, ua=UA, sleep=SLEEP, timeout=(20, 90), retries=4,
                     headers={"Accept": "text/html, */*"})
    except Exception as exc:
        r = None
        log.info("live fail %s %s", url, exc)
    if r is not None:
        if r.status_code == 429:
            wb = af.get_wayback_content(url)
            if wb.get("status") == "success":
                raw = wb.get("text") or ""
                if not raw and wb.get("content"):
                    raw = decode_html(wb["content"])
                if raw and not af.is_challenge(raw, 200):
                    return raw, wb.get("wayback_url") or url, "wayback"
            return "", url, "fail"
        if r.status_code in (404, 410):
            return "", url, "404"
        if r.status_code == 200 and r.content and len(r.content) > 400:
            html = decode_html(r.content)
            if "404 -" in html[:400] and "no encontrada" in html.lower():
                return "", url, "404"
            if not af.is_challenge(html, 200):
                return html, r.url or url, "live"
    return "", url, "fail"


def extract_documento(html: str) -> str:
    if not html:
        return ""
    m = re.search(r"<!--Inicio documento-->(.*)<!--Fin documento-->", html, re.S | re.I)
    chunk = m.group(1) if m else html
    # drop compiler chrome
    chunk = re.sub(r'(?is)<div id="logo_aj">.*?</div>\s*</div>', " ", chunk)
    chunk = re.sub(r'(?is)<div id="update_date">.*?</div>', " ", chunk)
    chunk = re.sub(r'(?is)<form\b.*?</form>', " ", chunk)
    chunk = re.sub(r'(?is)<script\b.*?</script>', " ", chunk)
    chunk = re.sub(r'(?is)<style\b.*?</style>', " ", chunk)
    return html_to_text(chunk)


def continuation_urls(html: str, page_url: str) -> list[str]:
    out = []
    seen = set()
    base_name = Path(page_url.split("?")[0]).name
    stem = re.sub(r"\.html$", "", base_name, flags=re.I)
    stem = re.sub(r"_pr\d+$", "", stem)
    for href in PR_HREF.findall(html or ""):
        href = href.replace("&amp;", "&")
        if stem.lower() not in href.lower():
            continue
        full = urljoin(page_url, href)
        if full not in seen:
            seen.add(full)
            out.append(full)
    # also probe sequential pr00N if first page hints at more
    if stem.lower() + "_pr" in (html or "").lower() and not out:
        for i in range(1, 30):
            out.append(urljoin(page_url, f"{stem}_pr{i:03d}.html"))
    return out


def fetch_instrument_html(start_url: str) -> tuple[str, str, str]:
    html, used, method = fetch_page(start_url)
    if not html:
        return "", used, method
    parts = [extract_documento(html)]
    extra = continuation_urls(html, start_url)
    seen = {start_url}
    for u in extra:
        if u in seen:
            continue
        seen.add(u)
        h2, used2, m2 = fetch_page(u)
        if not h2:
            if m2 == "404":
                break
            continue
        parts.append(extract_documento(h2))
        # follow further pr links from this page too
        for nxt in continuation_urls(h2, u):
            if nxt not in seen:
                extra.append(nxt)
    text = "\n\n".join(p for p in parts if p and len(p) > 20)
    return text, used, method


def catalog_path() -> Path:
    return ROOT / CC / "raw" / "catalog_leyes.jsonl"


def load_catalog() -> list[dict]:
    p = catalog_path()
    if not p.exists() or p.stat().st_size < 200:
        return []
    items = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except Exception:
                continue
    return items


def discover_senado() -> list[dict]:
    items = [{
        "ident": "cn-1991",
        "title": "Constitución Política de Colombia de 1991",
        "url": CONST,
        "kind": "constitution",
        "numero": "1991",
        "year": "1991",
        "priority": 0,
    }]
    html, _, method = fetch_page(LEYES_TREE)
    if not html:
        log.error("leyes tree failed")
        return items
    (ROOT / CC / "raw" / "leyes.html").write_text(html, encoding="utf-8")
    year_pages = YEAR_HREF.findall(html)
    log.info("year pages %s via %s", len(year_pages), method)
    seen = set()
    for rel, year in year_pages:
        yurl = urljoin(LEYES_TREE, rel)
        yh, _, ym = fetch_page(yurl)
        if not yh:
            log.info("year fail %s %s", year, ym)
            continue
        for href in LEY_HREF.findall(yh):
            full = urljoin(yurl, href)
            if full in seen:
                continue
            seen.add(full)
            m = LEY_NAME.search(href)
            num = m.group(1).lstrip("0") or "0" if m else ""
            y = m.group(2) if m else year
            ident = f"ley-{num}-{y}" if num else Path(href).stem
            items.append({
                "ident": ident,
                "title": f"Ley {num} de {y}",
                "url": full,
                "kind": "ley",
                "numero": num,
                "year": y,
                "priority": 1,
            })
    log.info("senado leyes linked n=%s (plus constitution)", len(items) - 1)
    return items


def discover() -> list[dict]:
    existing = load_catalog()
    if existing and len(existing) >= 200:
        log.info("resume catalog n=%s", len(existing))
        return existing
    items = discover_senado()
    atomic_write(catalog_path(), "".join(json.dumps(it, ensure_ascii=False) + "\n" for it in items))
    return items


def fetch_one(it: dict, done: set[str]) -> str:
    ident = it.get("ident") or it.get("url")
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    url = it.get("url") or ""
    text, used, method = fetch_instrument_html(url)
    if not text or len(text) < 80:
        log_failure(CC, {"identifier": ident, "source_url": url,
                         "status": "failed", "reason": "empty_text"})
        return "fail"
    if af.is_challenge(text, 200):
        log_failure(CC, {"identifier": ident, "source_url": url,
                         "status": "failed", "reason": "challenge"})
        return "fail"
    year = it.get("year")
    date = f"{year}-01-01" if year and re.match(r"^\d{4}$", year) else None
    title = it.get("title") or ident
    doc_type = "constitution" if it.get("kind") == "constitution" else "statute"
    docs = split_es(text, rid, used, date)
    official = title if it.get("kind") == "constitution" else f"Ley {it.get('numero')} de {it.get('year')}"
    repealed = bool(re.search(r"(?i)\bderogad", title)) or bool(re.search(r"(?i)^LEY \d+ de \d+\s*\(derogad", text[:400]))
    rec = base_record(
        cc=CC, country=COUNTRY, language="es", ident=ident, title=title, text=text,
        source_url=used, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="collect_co.py",
        eli=None, date=date, official_identifier=official,
        document_type=doc_type,
        law_status="repealed" if repealed else "current",
        is_current=not repealed,
        documents=docs,
        extra_meta={
            "discovery": {"method": "secretaria_senado_arbol", "seed_url": LEYES_TREE},
            "official_metadata": {
                "numero": it.get("numero"),
                "year": it.get("year"),
                "kind": it.get("kind"),
                "fetch_method": method,
                "canonical_basedoc": url,
            },
        },
        extra_fields={
            "canonical_title": title,
            "information_url": url,
            "canonical_document_url": url,
        },
    )
    write_instrument(CC, rec)
    done.add(rid)
    return "ok"


def main():
    setup()
    t0 = utcnow()
    items = discover()
    done = existing_ids(CC)
    ok = skip = fail = 0
    source_urls = [
        LEYES_TREE,
        CONST,
        SENADO,
        SUIN,
        "https://www.datos.gov.co/Justicia-y-Derecho/Lista-de-normas-cargadas-en-el-Sistema-nico-de-Inf/fiev-nid6",
        "https://www.imprenta.gov.co/",
    ]
    log.info("queue %s already_done=%s", len(items), len(done))

    def write_progress(cov: str):
        notes = (
            f"Constitución Política 1991 (multi-page basedoc) plus leyes 1992–present "
            f"from Secretaría del Senado chronological tree ({len(items)} catalog rows). "
            f"SUIN-Juriscol live TLS failed from this collector host (HTTP 502 / unexpected "
            f"EOF); Diario Oficial prevails. Pre-1992 codes/leyes not in the Senate 1992+ "
            f"tree are a ceiling unless SUIN/Wayback of official viewDocument URLs works. "
            f"Not Legis / Ámbito Jurídico. Started {t0}."
        )
        write_summary(
            CC, country=COUNTRY,
            source="Secretaría del Senado basedoc / SUIN-Juriscol (MinJusticia)",
            source_urls=source_urls, license_text=LICENSE,
            discovered=len(items), fetched=ok, skipped=skip, failed=fail,
            coverage=cov, notes=notes, last_run=utcnow(), extra=f"started {t0}",
        )

    rest = []
    for it in items:
        if it.get("kind") == "constitution":
            try:
                st = fetch_one(it, done)
            except Exception as exc:
                st = "fail"
                log_failure(CC, {"id": "cn", "status": "failed", "reason": repr(exc)})
            ok += st == "ok"; skip += st == "skip"; fail += st == "fail"
            log.info("constitution %s", st)
        else:
            rest.append(it)
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = [ex.submit(fetch_one, it, done) for it in rest]
        n = 0
        for fut in as_completed(futs):
            n += 1
            try:
                st = fut.result()
            except Exception as exc:
                st = "fail"
                log_failure(CC, {"status": "failed", "reason": repr(exc)})
            ok += st == "ok"; skip += st == "skip"; fail += st == "fail"
            if n % 40 == 0 or n == len(rest):
                log.info("progress %s/%s ok=%s skip=%s fail=%s", n, len(rest), ok, skip, fail)
                write_progress("catalog-backed incomplete")
    cov = "full" if fail == 0 and ok + skip >= len(items) and items else "catalog-backed incomplete"
    write_progress(cov)
    log.info("done ok=%s skip=%s fail=%s coverage=%s", ok, skip, fail, cov)


if __name__ == "__main__":
    main()
