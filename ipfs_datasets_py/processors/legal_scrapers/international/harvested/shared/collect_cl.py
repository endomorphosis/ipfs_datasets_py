#!/usr/bin/env python3
"""Chile: Constitución + leyes nacionales from official Ley Chile / BCN.

Official sources only:
  - Ley Chile / Biblioteca del Congreso Nacional
    https://www.bcn.cl/leychile  https://www.leychile.cl/
    XML: https://www.leychile.cl/Consulta/obtxml?opt=7&idNorma=...|&idLey=...
  - BCN Linked Open Data SPARQL https://datos.bcn.cl/sparql
  - Diario Oficial if needed for authentic text

National in-force laws first (Constitución + Ley). Does not use commercial DBs.
No WAF bypass. archive_fallbacks.py on HTTP 429 / BCN service-limit.
"""
from __future__ import annotations

import json
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af

CC = "cl"
COUNTRY = "Chile"
SOURCE_TYPE = "leychile_bcn"
LICENSE = (
    "Official Chilean legislative texts published by the Biblioteca del Congreso "
    "Nacional (Ley Chile / BCN). Reuse under BCN/Ley Chile terms. The BCN / Diario "
    "Oficial authentic text prevails. Not legal advice."
)
UA = DEFAULT_UA + " source=https://www.bcn.cl/leychile"
OBTXML = "https://www.leychile.cl/Consulta/obtxml"
SPARQL = "https://datos.bcn.cl/sparql"
CONST_IDNORMA = "242302"  # Decreto 100: texto refundido Constitución Política
WORKERS = 2
SLEEP = 0.7  # BCN XML service-limits quickly
SPARQL_SLEEP = 10.0  # robots.txt Crawl-delay: 10 on datos.bcn.cl
log = logging.getLogger("cl")
_wb_fail = 0

ART_CL = re.compile(
    r"(?im)^\s*((?:Art[íi]culo|ART[IÍ]CULO|Art\.?)\s+"
    r"[\d]+[ºo°]?[A-Za-z]?(?:\s*(?:bis|ter|qu[aá]ter|transitori[oa]s?))?)\b"
)


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
    if len(docs) >= 2:
        return docs
    matches = list(ART_CL.finditer(text or ""))
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
            "metadata": {"text_extraction": {"source": "official", "backend": "leychile_xml"}},
        })
        if len(out) >= 4000:
            break
    return out if len(out) >= 2 else []


def parse_xml(raw: bytes) -> dict:
    if not raw or b"<Norma" not in raw[:500] and b"<norma" not in raw[:500].lower():
        return {}
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return {}
    der = (root.attrib.get("derogado") or "").lower()
    nid = root.attrib.get("normaId") or ""
    fecha_ver = root.attrib.get("fechaVersion") or ""
    title = ""
    numero = ""
    tipo = ""
    pub = root.attrib.get("fechaPublicacion") or ""
    prom = ""
    texts: list[str] = []
    arts: list[tuple[str, str]] = []

    def loc(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    ident = root.find(".//{http://www.leychile.cl/esquemas}Identificador")
    if ident is not None:
        pub = ident.attrib.get("fechaPublicacion") or pub
        prom = ident.attrib.get("fechaPromulgacion") or prom

    for el in root.iter():
        t = loc(el.tag)
        if t == "TituloNorma" and (el.text or "").strip() and not title:
            title = el.text.strip()
        elif t == "Descripcion" and (el.text or "").strip() and not tipo:
            tipo = el.text.strip()
        elif t == "Numero" and (el.text or "").strip() and not numero:
            numero = el.text.strip()
        elif t == "Texto" and (el.text or "").strip():
            texts.append(el.text.strip())
        elif t == "EstructuraFuncional" and (el.attrib.get("tipoParte") or "") == "Artículo":
            body = ""
            for child in el:
                if loc(child.tag) == "Texto" and (child.text or "").strip():
                    body = child.text.strip()
                    break
            if body:
                m = ART_CL.search(body)
                label = m.group(1) if m else "Artículo"
                arts.append((label, body))

    full = "\n\n".join(texts).strip()
    return {
        "norma_id": nid,
        "title": title,
        "numero": numero,
        "tipo": tipo,
        "derogado": der,
        "fecha_version": fecha_ver,
        "fecha_publicacion": pub,
        "fecha_promulgacion": prom,
        "text": full,
        "xml_articles": arts,
    }


def is_xml_payload(body: bytes) -> bool:
    if not body:
        return False
    head = body.lstrip()[:800]
    return head.startswith(b"<?xml") or b"<Norma" in head or b"<NORMAS" in head or b"<Categorias" in head


def fetch_xml_bytes(url: str) -> tuple[bytes, str, str]:
    try:
        r = http_get(url, ua=UA, sleep=SLEEP, timeout=(20, 60), retries=2, allow_empty=True,
                     headers={"Accept": "application/xml, text/xml, */*"})
    except Exception as exc:
        r = None
        log.info("live xml fail %s %s", url, exc)
    if r is not None:
        body = r.content or b""
        limited = r.status_code == 429 or body[:80].find(b"Service limit") >= 0
        if limited:
            global _wb_fail
            if _wb_fail >= 4:
                return b"", url, "fail"
            wb = af.get_wayback_content(url)
            if wb.get("status") == "success":
                content = wb.get("content") or b""
                if not content and wb.get("text"):
                    content = wb["text"].encode("utf-8", "replace")
                if is_xml_payload(content):
                    _wb_fail = 0
                    return content, wb.get("wayback_url") or url, "wayback"
            err = str(wb.get("error") or "")
            if "SSL" in err or "UNEXPECTED_EOF" in err or err.startswith("http_"):
                _wb_fail += 1
            return b"", url, "fail"
        if r.status_code in (404, 410):
            return b"", url, "404"
        if r.status_code == 200 and is_xml_payload(body):
            return body, r.url or url, "live"
        log.info("live xml status=%s bytes=%s %s", r.status_code, len(body), url)
    return b"", url, "fail"


def xml_url(id_norma: Optional[str] = None, id_ley: Optional[str] = None) -> str:
    if id_norma:
        return f"{OBTXML}?opt=7&idNorma={id_norma}"
    return f"{OBTXML}?opt=7&idLey={id_ley}"


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


def sparql_page(offset: int, limit: int = 4000) -> list[dict]:
    query = f"""PREFIX dc: <http://purl.org/dc/elements/1.1/>
PREFIX bcnnorms: <http://datos.bcn.cl/ontologies/bcn-norms#>
SELECT ?norma ?id ?title WHERE {{
  ?norma a bcnnorms:Norm .
  ?norma dc:identifier ?id .
  OPTIONAL {{ ?norma dc:title ?title }}
  FILTER regex(str(?norma), "/recurso/cl/ley/")
}} LIMIT {int(limit)} OFFSET {int(offset)}"""
    import time as _t
    _t.sleep(SPARQL_SLEEP)
    try:
        r = get_session(UA).post(
            SPARQL,
            data={"query": query, "format": "json"},
            timeout=(20, 120),
            headers={"Accept": "application/sparql-results+json, application/json", "User-Agent": UA},
        )
    except Exception as exc:
        log.warning("sparql offset=%s %s", offset, exc)
        return []
    if r.status_code == 429:
        log.info("sparql 429 offset=%s -> wayback not applicable; backoff", offset)
        _t.sleep(20)
        return []
    if r.status_code != 200 or not r.content:
        log.info("sparql HTTP %s offset=%s", r.status_code, offset)
        return []
    try:
        data = r.json()
    except Exception:
        return []
    out = []
    for b in (data.get("results") or {}).get("bindings") or []:
        uri = ((b.get("norma") or {}).get("value") or "")
        nid = ((b.get("id") or {}).get("value") or "")
        title = ((b.get("title") or {}).get("value") or "")
        if not uri:
            continue
        out.append({"uri": uri, "id_norma": nid, "title": title})
    return out


def parse_ley_uri(uri: str) -> dict:
    # http://datos.bcn.cl/recurso/cl/ley/{org}/{date}/{number}[/es@date]
    m = re.search(r"/recurso/cl/ley/([^/]+)/(\d{4}-\d{2}-\d{2})/(\d+)(?:/|$)", uri or "")
    if not m:
        m2 = re.search(r"/recurso/cl/ley/.*/(\d+)(?:/es@|$)", uri or "")
        return {"numero": m2.group(1) if m2 else "", "dated": "@" in (uri or "")}
    return {"org": m.group(1), "date": m.group(2), "numero": m.group(3), "dated": "/es@" in uri}


def discover_sparql() -> list[dict]:
    by_num: dict[str, dict] = {}
    offset = 0
    empty = 0
    while offset < 80_000:
        batch = sparql_page(offset, 4000)
        if not batch:
            empty += 1
            if empty >= 2:
                break
            offset += 4000
            continue
        empty = 0
        for rec in batch:
            meta = parse_ley_uri(rec["uri"])
            num = meta.get("numero") or ""
            if not num:
                continue
            # prefer non-language-version URI
            prev = by_num.get(num)
            if prev and meta.get("dated") and not prev.get("dated"):
                continue
            by_num[num] = {
                "numero": num,
                "id_norma": rec.get("id_norma") or "",
                "title": rec.get("title") or "",
                "uri": rec["uri"],
                "dated": bool(meta.get("dated")),
                "kind": "ley",
                "priority": 2,
            }
        log.info("sparql offset=%s batch=%s unique_leyes=%s", offset, len(batch), len(by_num))
        if len(batch) < 4000:
            break
        offset += 4000
    return list(by_num.values())


def discover_category() -> list[dict]:
    url = f"{OBTXML}?opt=6&idCategoria=1"
    raw, used, method = fetch_xml_bytes(url)
    if not raw:
        return []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []
    items = []
    for norma in root.iter():
        if norma.tag.rsplit("}", 1)[-1] != "NORMA":
            continue
        url_el = None
        desc = ""
        num = ""
        title = ""
        for child in list(norma):
            t = child.tag.rsplit("}", 1)[-1]
            if t == "URL":
                url_el = (child.text or "").strip()
            elif t == "TITULO":
                title = (child.text or "").strip()
            elif t == "TIPOS_NUMEROS":
                for tn in child.iter():
                    tt = tn.tag.rsplit("}", 1)[-1]
                    if tt == "DESCRIPCION" and (tn.text or "").strip():
                        desc = tn.text.strip()
                    if tt == "NUMERO" and (tn.text or "").strip():
                        num = tn.text.strip()
        if desc.lower() != "ley":
            continue
        m = re.search(r"idNorma=(\d+)", url_el or "")
        nid = m.group(1) if m else ""
        items.append({
            "numero": num, "id_norma": nid, "title": title, "uri": url_el,
            "kind": "ley", "priority": 1, "source": "categoria_1",
        })
    log.info("category-1 leyes n=%s method=%s", len(items), method)
    return items


def latest_ley_number() -> int:
    url = f"{OBTXML}?opt=3"
    raw, _, method = fetch_xml_bytes(url)
    best = 21837
    if not raw:
        return best
    for m in re.finditer(r"<NUMERO>(\d+)</NUMERO>", raw.decode("utf-8", "replace")):
        try:
            best = max(best, int(m.group(1)))
        except Exception:
            pass
    log.info("latest ley number ~%s via %s", best, method)
    return best


def discover() -> list[dict]:
    existing = load_catalog()
    if existing and len(existing) >= 500:
        log.info("resume catalog n=%s", len(existing))
        return existing
    items: dict[str, dict] = {}

    def add(it: dict):
        key = str(it.get("id_norma") or "") or f"ley-{it.get('numero')}"
        if not key or key == "ley-":
            return
        prev = items.get(key)
        if prev and (prev.get("priority", 9) <= it.get("priority", 9)):
            if it.get("title") and not prev.get("title"):
                prev["title"] = it["title"]
            if it.get("id_norma") and not prev.get("id_norma"):
                prev["id_norma"] = it["id_norma"]
            return
        items[key] = it

    add({
        "id_norma": CONST_IDNORMA, "numero": "100", "title": "Constitución Política de la República de Chile",
        "kind": "constitution", "priority": 0, "ident": "cn-1980",
    })
    for it in discover_category():
        add(it)
    try:
        for it in discover_sparql():
            add(it)
    except Exception as exc:
        log.warning("sparql discover failed: %s", exc)
    if len(items) < 200:
        # range fallback: numbered leyes 1..latest (many 404 / derogated)
        latest = latest_ley_number()
        log.info("idLey range fallback 1..%s", latest)
        for n in range(1, latest + 1):
            add({"numero": str(n), "id_norma": "", "kind": "ley", "priority": 3, "ident": f"ley-{n}"})
    out = list(items.values())
    out.sort(key=lambda x: (x.get("priority", 9), int(re.sub(r"\D", "", x.get("numero") or "0") or 0)))
    atomic_write(catalog_path(), "".join(json.dumps(it, ensure_ascii=False) + "\n" for it in out))
    log.info("discovered n=%s", len(out))
    return out


def fetch_one(it: dict, done: set[str]) -> str:
    nid = (it.get("id_norma") or "").strip()
    num = (it.get("numero") or "").strip()
    ident = it.get("ident") or (f"cn-1980" if it.get("kind") == "constitution" else f"ley-{num or nid}")
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    urls = []
    if nid:
        urls.append(xml_url(id_norma=nid))
    if num and num.isdigit():
        urls.append(xml_url(id_ley=num))
    parsed = {}
    used = ""
    method = "fail"
    for u in urls:
        raw, used, method = fetch_xml_bytes(u)
        if not raw:
            continue
        parsed = parse_xml(raw)
        if parsed.get("text") and len(parsed["text"]) >= 40:
            break
        parsed = {}
    if not parsed or not parsed.get("text") or len(parsed["text"]) < 40:
        log_failure(CC, {"identifier": ident, "source_url": urls[0] if urls else "",
                         "status": "failed", "reason": "empty_xml"})
        return "fail"
    der = (parsed.get("derogado") or "").lower()
    if "derogado" in der and der != "no derogado":
        # still keep in-force-first by skipping fully repealed instruments
        log_failure(CC, {"identifier": ident, "source_url": used,
                         "status": "skipped_repealed", "reason": parsed.get("derogado")})
        return "skip"
    text = parsed["text"]
    date = iso_date(parsed.get("fecha_version") or parsed.get("fecha_publicacion") or parsed.get("fecha_promulgacion"))
    title = it.get("title") or parsed.get("title") or ident
    if it.get("kind") == "constitution" or "constituci" in title.lower():
        title = parsed.get("title") or "Constitución Política de la República de Chile"
        doc_type = "constitution"
    else:
        doc_type = "statute"
    docs = []
    for label, body in parsed.get("xml_articles") or []:
        aid = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
        docs.append({
            "id": f"{rid}-{aid}"[:180], "title": body.split("\n", 1)[0][:200],
            "text": body, "date_filed": date, "document_number": label,
            "source_url": used, "record_type": "article", "article_number": label,
            "law_identifier": rid,
            "metadata": {"text_extraction": {"source": "official", "backend": "leychile_xml"}},
        })
        if len(docs) >= 4000:
            break
    if len(docs) < 2:
        docs = split_es(text, rid, used, date)
    official = parsed.get("numero") or num or nid
    if parsed.get("tipo"):
        official = f"{parsed['tipo']} {official}".strip()
    rec = base_record(
        cc=CC, country=COUNTRY, language="es", ident=ident, title=title, text=text,
        source_url=used, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="collect_cl.py",
        eli=f"https://www.leychile.cl/Navegar?idNorma={parsed.get('norma_id') or nid}",
        date=date, official_identifier=official,
        document_type=doc_type, law_status="current", is_current=True,
        documents=docs,
        extra_meta={
            "discovery": {"method": "bcn_sparql_or_obtxml", "id_norma": parsed.get("norma_id") or nid,
                          "numero": parsed.get("numero") or num},
            "official_metadata": {
                "norma_id": parsed.get("norma_id"),
                "tipo": parsed.get("tipo"),
                "derogado": parsed.get("derogado"),
                "fecha_version": parsed.get("fecha_version"),
                "fecha_publicacion": parsed.get("fecha_publicacion"),
                "fecha_promulgacion": parsed.get("fecha_promulgacion"),
                "fetch_method": method,
            },
        },
        extra_fields={
            "canonical_title": title,
            "publication_date": iso_date(parsed.get("fecha_publicacion")),
            "information_url": f"https://www.leychile.cl/Navegar?idNorma={parsed.get('norma_id') or nid}",
            "canonical_document_url": xml_url(id_norma=parsed.get("norma_id") or nid) if (parsed.get("norma_id") or nid) else used,
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
        "https://www.bcn.cl/leychile",
        "https://www.leychile.cl/",
        "https://www.leychile.cl/Consulta/obtxml?opt=7",
        "https://datos.bcn.cl/sparql",
    ]
    log.info("queue %s already_done=%s", len(items), len(done))

    def write_progress(cov: str):
        notes = (
            f"Constitución (idNorma {CONST_IDNORMA}, Decreto 100 texto refundido) plus "
            f"national Leyes from BCN SPARQL (/recurso/cl/ley/) and Ley Chile obtxml. "
            f"Fully repealed XML (derogado) skipped. Live XML 429 uses archive_fallbacks "
            f"on the official obtxml URL (no WAF bypass; Navegar is an SPA shell and is "
            f"not scraped). Ceiling: SPARQL/XML service limits and Wayback coverage of "
            f"official URLs. Started {t0}."
        )
        write_summary(
            CC, country=COUNTRY,
            source="Ley Chile / Biblioteca del Congreso Nacional (BCN)",
            source_urls=source_urls, license_text=LICENSE,
            discovered=len(items), fetched=ok, skipped=skip, failed=fail,
            coverage=cov, notes=notes, last_run=utcnow(), extra=f"started {t0}",
        )

    # Constitution first (sequential), then the rest.
    rest = []
    for it in items:
        if it.get("kind") == "constitution" or it.get("id_norma") == CONST_IDNORMA:
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
            if n % 25 == 0 or n == len(rest):
                log.info("progress %s/%s ok=%s skip=%s fail=%s", n, len(rest), ok, skip, fail)
                write_progress("catalog-backed incomplete")
    cov = "full" if fail == 0 and ok + skip >= len(items) and items else "catalog-backed incomplete"
    write_progress(cov)
    log.info("done ok=%s skip=%s fail=%s coverage=%s", ok, skip, fail, cov)


if __name__ == "__main__":
    main()
