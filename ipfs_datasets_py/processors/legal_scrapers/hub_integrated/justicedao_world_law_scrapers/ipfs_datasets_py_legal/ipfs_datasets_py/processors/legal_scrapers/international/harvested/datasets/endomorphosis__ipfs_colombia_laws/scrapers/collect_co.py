#!/usr/bin/env python3
"""Colombia: Constitución + leyes + códigos/estatutos + actos legislativos.

Official sources only:
  - Secretaría del Senado / Congreso basedoc consolidations
    http://www.secretariasenado.gov.co/senado/basedoc/
  - SUIN-Juriscol https://www.suin-juriscol.gov.co (MinJusticia) when reachable
  - Diario Oficial / Imprenta Nacional https://www.imprenta.gov.co if needed
  - datos.gov.co catalog of SUIN-loaded norms (metadata only)

Lean deepen: códigos/estatutos nacionales + actos legislativos + leyes tree.
Not Legis or Ámbito Jurídico. No WAF bypass. No CC/WARC.
archive_fallbacks.py on HTTP 429. SUIN live TLS often fails from this host;
Wayback of official SUIN URLs is used only as a fallback.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
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
    "of the Constitución, leyes, códigos/estatutos and actos legislativos; the Diario "
    "Oficial authentic text prevails. Editorial notes of the compiler are not a "
    "substitute for the gazette. Not legal advice."
)
UA = DEFAULT_UA + " source=http://www.secretariasenado.gov.co/senado/basedoc/"
SENADO = "http://www.secretariasenado.gov.co/senado/basedoc/"
LEYES_TREE = SENADO + "arbol/leyes.html"
CODIGOS_TREE = SENADO + "arbol/7772.html"  # CÓDIGOS Y ESTATUTOS NACIONALES
ACTOS_TREE = SENADO + "arbol/16263.html"  # ACTOS LEGISLATIVOS
CONST = SENADO + "constitucion_politica_1991.html"
SUIN = "https://www.suin-juriscol.gov.co/"
DATOS = "https://www.datos.gov.co/resource/fiev-nid6.json"
WORKERS = 4
SLEEP = 0.35
log = logging.getLogger("co")

ART_CO = re.compile(
    r"(?im)^\s*((?:Art(?:[íi]culo|\.|iculo)?|ART[IÍ]CULO)\s+"
    r"[\d]+(?:[oº°.]|[A-Za-z])?(?:\s*(?:bis|ter|qu[aá]ter))?)\b"
)
PR_HREF = re.compile(r'href=["\']([^"\']+_pr\d+\.html)["\']', re.I)
PR_OPT = re.compile(r'value=["\'](_pr\d+)', re.I)
YEAR_HREF = re.compile(r'href=["\'](\d+\.html)["\'][^>]*>\s*LEYES\s+(\d{4})', re.I)
LEY_HREF = re.compile(r'href=["\'](\.\./(?:ley|decreto|codigo|estatuto|acto)[^"\']+\.html)["\']', re.I)
LEY_NAME = re.compile(r"ley_(\d+)_(\d{4})", re.I)
ACTO_NAME = re.compile(r"acto_legislativo_(\d+)_(\d{4})", re.I)
DECRETO_NAME = re.compile(r"decreto_(\d+)_(\d{4})", re.I)
DOC_HREF = re.compile(
    r'href=["\'](\.\./(?:ley_|decreto_|codigo_|estatuto_|acto_)[^"\']+\.html)["\']',
    re.I,
)
TITLE_HREF = re.compile(
    r'href=["\'](\.\./(?:ley_|decreto_|codigo_|estatuto_|acto_)[^"\']+\.html)["\'][^>]*>([^<]*)',
    re.I,
)


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)) or default)
    except Exception:
        return default


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
        return docs if len(docs) >= 2 else []
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
        if len(out) >= 5000:
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
    chunk = re.sub(r'(?is)<div id="logo_aj">.*?</div>\s*</div>', " ", chunk)
    chunk = re.sub(r'(?is)<div id="update_date">.*?</div>', " ", chunk)
    chunk = re.sub(r'(?is)<form\b.*?</form>', " ", chunk)
    chunk = re.sub(r'(?is)<script\b.*?</script>', " ", chunk)
    chunk = re.sub(r'(?is)<style\b.*?</style>', " ", chunk)
    # drop compiler chrome blocks that bloat article splits
    chunk = re.sub(r"(?is)<div[^>]*(?:jurisprudencia|notas_?editor|legislacion_anterior)[^>]*>.*?</div>", " ", chunk)
    return html_to_text(chunk)


def continuation_urls(html: str, page_url: str) -> list[str]:
    out = []
    seen = set()
    base_name = Path(page_url.split("?")[0]).name
    stem = re.sub(r"\.html$", "", base_name, flags=re.I)
    stem = re.sub(r"_pr\d+$", "", stem)

    def add(full: str):
        if full not in seen:
            seen.add(full)
            out.append(full)

    for href in PR_HREF.findall(html or ""):
        href = href.replace("&amp;", "&")
        if stem.lower() not in href.lower():
            continue
        add(urljoin(page_url, href))

    # select option values like value="_pr012" on multi-page códigos
    opts = sorted({int(m.group(1)) for m in re.finditer(r"_pr(\d+)", " ".join(PR_OPT.findall(html or "")))})
    for n in opts:
        add(urljoin(page_url, f"{stem}_pr{n:03d}.html"))

    if stem.lower() + "_pr" in (html or "").lower() and len(out) < 2:
        for i in range(1, 120):
            add(urljoin(page_url, f"{stem}_pr{i:03d}.html"))
    return out


def fetch_instrument_html(start_url: str, max_pages: int = 120) -> tuple[str, str, str]:
    html, used, method = fetch_page(start_url)
    if not html:
        return "", used, method
    parts = [extract_documento(html)]
    extra = continuation_urls(html, start_url)
    seen = {start_url}
    for u in extra:
        if len(parts) >= max_pages:
            break
        if u in seen:
            continue
        seen.add(u)
        h2, used2, m2 = fetch_page(u)
        if not h2:
            if m2 == "404":
                # sequential probe may overshoot; stop if many consecutive 404s later
                continue
            continue
        parts.append(extract_documento(h2))
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


def _ident_from_href(href: str, title: str = "") -> tuple[str, str, str, str]:
    """Return ident, kind, numero, year from basedoc href."""
    name = Path(href).name.lower()
    m = LEY_NAME.search(name)
    if m:
        num = m.group(1).lstrip("0") or "0"
        y = m.group(2)
        return f"ley-{num}-{y}", "ley", num, y
    m = ACTO_NAME.search(name)
    if m:
        num = m.group(1).lstrip("0") or "0"
        y = m.group(2)
        return f"acto-legislativo-{num}-{y}", "acto_legislativo", num, y
    m = DECRETO_NAME.search(name)
    if m:
        num = m.group(1).lstrip("0") or "0"
        y = m.group(2)
        return f"decreto-{num}-{y}", "decreto_codigo", num, y
    stem = Path(href).stem.lower()
    if stem.startswith("codigo_"):
        return f"codigo-{stem[7:].replace('_', '-')}", "codigo", "", ""
    if stem.startswith("estatuto_"):
        return f"estatuto-{stem[9:].replace('_', '-')}", "estatuto", "", ""
    return stem.replace("_", "-"), "instrument", "", ""


def discover_senado_leyes(existing_urls: set[str] | None = None) -> list[dict]:
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
    seen = set(existing_urls or [])
    for rel, year in year_pages:
        yurl = urljoin(LEYES_TREE, rel)
        yh, _, ym = fetch_page(yurl)
        if not yh:
            log.info("year fail %s %s", year, ym)
            continue
        for href in re.findall(r'href=["\'](\.\./ley_\d+_\d{4}\.html)["\']', yh, re.I):
            full = urljoin(yurl, href)
            if full in seen:
                continue
            seen.add(full)
            ident, kind, num, y = _ident_from_href(href)
            items.append({
                "ident": ident,
                "title": f"Ley {num} de {y}",
                "url": full,
                "kind": "ley",
                "numero": num,
                "year": y,
                "priority": 3,
            })
    log.info("senado leyes linked n=%s (plus constitution)", len(items) - 1)
    return items


def discover_codigos() -> list[dict]:
    html, _, method = fetch_page(CODIGOS_TREE)
    if not html:
        log.warning("codigos tree fail method=%s", method)
        return []
    (ROOT / CC / "raw" / "codigos_estatutos.html").write_text(html, encoding="utf-8")
    items = []
    seen = set()
    for href, title in TITLE_HREF.findall(html):
        full = urljoin(CODIGOS_TREE, href)
        if full in seen:
            continue
        seen.add(full)
        ident, kind, num, y = _ident_from_href(href, title)
        # Prefer named códigos/estatutos/decretos; ley_* already covered by leyes tree
        # but keep pre-1992 leyes (e.g. ley_0009_1979) that chronological tree misses.
        if kind == "ley" and y and y.isdigit() and int(y) >= 1992:
            continue
        title_clean = re.sub(r"\s+", " ", title or "").strip() or ident
        if kind == "ley":
            title_clean = f"Ley {num} de {y}" if num else title_clean
            pri = 1
        elif kind in ("codigo", "estatuto"):
            pri = 1
        elif kind == "decreto_codigo":
            pri = 1
            title_clean = title_clean or f"Decreto {num} de {y}"
        else:
            pri = 2
        items.append({
            "ident": ident,
            "title": title_clean[:300],
            "url": full,
            "kind": kind,
            "numero": num,
            "year": y,
            "priority": pri,
        })
    log.info("codigos/estatutos n=%s via %s", len(items), method)
    return items


def discover_actos() -> list[dict]:
    html, _, method = fetch_page(ACTOS_TREE)
    if not html:
        log.warning("actos tree fail method=%s", method)
        return []
    (ROOT / CC / "raw" / "actos_legislativos.html").write_text(html, encoding="utf-8")
    year_pages = re.findall(r'href=["\'](\d+\.html)["\'][^>]*>\s*(\d{4})', html)
    items = []
    seen = set()
    for rel, year in year_pages:
        yurl = urljoin(ACTOS_TREE, rel)
        yh, _, ym = fetch_page(yurl)
        if not yh:
            log.info("actos year fail %s %s", year, ym)
            continue
        for href, title in TITLE_HREF.findall(yh):
            if "acto_legislativo" not in href.lower():
                continue
            full = urljoin(yurl, href)
            if full in seen:
                continue
            seen.add(full)
            ident, kind, num, y = _ident_from_href(href, title)
            title_clean = re.sub(r"\s+", " ", title or "").strip() or f"Acto Legislativo {num} de {y}"
            items.append({
                "ident": ident,
                "title": title_clean[:300],
                "url": full,
                "kind": "acto_legislativo",
                "numero": num,
                "year": y or year,
                "priority": 1,
            })
    log.info("actos legislativos n=%s via %s", len(items), method)
    return items


def discover() -> list[dict]:
    """Merge prior catalog with fresh códigos/actos and leyes rediscovery."""
    by_url: dict[str, dict] = {}
    for it in load_catalog():
        u = it.get("url") or ""
        if u:
            by_url[u] = it
    # Always deepen: códigos + actos (lean, high value)
    for it in discover_codigos():
        by_url[it["url"]] = it
    for it in discover_actos():
        by_url[it["url"]] = it
    # Refresh leyes tree for any new rows (also fills constitution)
    for it in discover_senado_leyes(existing_urls=set(by_url)):
        u = it["url"]
        if u not in by_url:
            by_url[u] = it
        elif it.get("kind") == "constitution":
            by_url[u] = it
    items = list(by_url.values())
    items.sort(key=lambda d: (d.get("priority", 9), d.get("kind") or "", d.get("year") or "", d.get("ident") or ""))
    atomic_write(catalog_path(), "".join(json.dumps(it, ensure_ascii=False) + "\n" for it in items))
    log.info("merged catalog n=%s", len(items))
    return items


def fetch_one(it: dict, done: set[str]) -> str:
    ident = it.get("ident") or it.get("url")
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    url = it.get("url") or ""
    # Código Civil / Comercio etc. can be large; allow many pr pages
    max_pages = 120 if it.get("kind") in ("codigo", "estatuto", "decreto_codigo", "constitution") else 40
    text, used, method = fetch_instrument_html(url, max_pages=max_pages)
    if not text or len(text) < 80:
        log_failure(CC, {"identifier": ident, "source_url": url,
                         "status": "failed", "reason": "empty_text"})
        return "fail"
    if af.is_challenge(text, 200):
        log_failure(CC, {"identifier": ident, "source_url": url,
                         "status": "failed", "reason": "challenge"})
        return "fail"
    year = it.get("year")
    date = f"{year}-01-01" if year and re.match(r"^\d{4}$", str(year)) else None
    title = it.get("title") or ident
    kind = it.get("kind") or "ley"
    if kind == "constitution":
        doc_type = "constitution"
    elif kind == "acto_legislativo":
        doc_type = "constitutional_amendment"
    elif kind in ("codigo", "estatuto", "decreto_codigo"):
        doc_type = "code"
    else:
        doc_type = "statute"
    docs = split_es(text, rid, used, date)
    if kind == "constitution":
        official = title
    elif kind == "acto_legislativo":
        official = f"Acto Legislativo {it.get('numero')} de {it.get('year')}"
    elif kind == "decreto_codigo":
        official = f"Decreto {it.get('numero')} de {it.get('year')}"
    elif kind in ("codigo", "estatuto"):
        official = title
    else:
        official = f"Ley {it.get('numero')} de {it.get('year')}"
    repealed = bool(re.search(r"(?i)\bderogad", title)) or bool(
        re.search(r"(?i)^LEY \d+ de \d+\s*\(derogad", text[:400])
    )
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
            "discovery": {
                "method": "secretaria_senado_arbol",
                "seed_url": LEYES_TREE,
                "deepen": "codigos_actos_20260910",
            },
            "official_metadata": {
                "numero": it.get("numero"),
                "year": it.get("year"),
                "kind": kind,
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
    t_start = time.time()
    max_new = env_int("MAX_NEW", 80)
    max_seconds = env_int("MAX_SECONDS", 4200)
    items = discover()
    done = existing_ids(CC)
    ok = skip = fail = 0
    source_urls = [
        LEYES_TREE,
        CODIGOS_TREE,
        ACTOS_TREE,
        CONST,
        SENADO,
        SUIN,
        "https://www.datos.gov.co/Justicia-y-Derecho/Lista-de-normas-cargadas-en-el-Sistema-nico-de-Inf/fiev-nid6",
        "https://www.imprenta.gov.co/",
    ]
    log.info("queue %s already_done=%s max_new=%s max_seconds=%s",
             len(items), len(done), max_new, max_seconds)

    def write_progress(cov: str):
        notes = (
            f"Constitución Política 1991 + leyes 1992–present + códigos/estatutos "
            f"(arbol/7772) + actos legislativos (arbol/16263) from Secretaría del Senado "
            f"({len(items)} catalog rows). Lean deepen 2026-09-10. SUIN-Juriscol live TLS "
            f"often fails; Diario Oficial prevails. Not Legis / Ámbito Jurídico. "
            f"Started {t0}."
        )
        write_summary(
            CC, country=COUNTRY,
            source="Secretaría del Senado basedoc / SUIN-Juriscol (MinJusticia)",
            source_urls=source_urls, license_text=LICENSE,
            discovered=len(items), fetched=ok, skipped=skip, failed=fail,
            coverage=cov, notes=notes, last_run=utcnow(), extra=f"started {t0}",
        )

    # Priority order already sorted; fetch sequentially for códigos (large) then pool leyes
    pending = []
    for it in items:
        rid = slug_id(CC, it.get("ident") or it.get("url"))
        if rid in done:
            skip += 1
            continue
        pending.append(it)

    log.info("pending_new=%s (after skip=%s)", len(pending), skip)
    # Fetch high-priority (códigos/actos) first, single-threaded to be polite on huge codes
    hi = [it for it in pending if (it.get("priority") or 9) <= 1]
    lo = [it for it in pending if (it.get("priority") or 9) > 1]
    for it in hi:
        if ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        try:
            st = fetch_one(it, done)
        except Exception as exc:
            st = "fail"
            log_failure(CC, {"id": it.get("ident"), "status": "failed", "reason": repr(exc)})
        ok += st == "ok"
        fail += st == "fail"
        skip += st == "skip"
        log.info("hi %s %s arts_pending ok=%s", it.get("ident"), st, ok)
        if ok % 5 == 0:
            write_progress("catalog-backed incomplete")

    rest = lo
    if ok < max_new and time.time() - t_start < max_seconds and rest:
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futs = {}
            for it in rest:
                if ok + len(futs) >= max_new:
                    break
                if time.time() - t_start > max_seconds:
                    break
                futs[ex.submit(fetch_one, it, done)] = it
            n = 0
            for fut in as_completed(futs):
                n += 1
                try:
                    st = fut.result()
                except Exception as exc:
                    st = "fail"
                    log_failure(CC, {"status": "failed", "reason": repr(exc)})
                ok += st == "ok"
                fail += st == "fail"
                skip += st == "skip"
                if n % 20 == 0 or n == len(futs):
                    log.info("lo progress %s/%s ok=%s skip=%s fail=%s", n, len(futs), ok, skip, fail)
                    write_progress("catalog-backed incomplete")
                if time.time() - t_start > max_seconds:
                    break

    cov = "full" if fail == 0 and ok + skip >= len(items) and items else "catalog-backed incomplete"
    write_progress(cov)
    log.info("done ok=%s skip=%s fail=%s coverage=%s", ok, skip, fail, cov)


if __name__ == "__main__":
    main()
