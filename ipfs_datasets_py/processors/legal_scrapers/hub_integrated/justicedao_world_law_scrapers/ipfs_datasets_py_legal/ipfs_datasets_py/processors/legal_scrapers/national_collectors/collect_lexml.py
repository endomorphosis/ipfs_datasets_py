#!/usr/bin/env python3
"""Brazil: Constituição + leis ordinárias/complementares from official sources.

Official sources only:
  - LexML Brasil URNs: https://www.lexml.gov.br/urn/...  (robots.txt Allow: /urn)
  - Senado Dados Abertos catalog XML:
    https://legis.senado.leg.br/dadosabertos/legislacao/lista?tipo=LEI
    https://legis.senado.leg.br/dadosabertos/legislacao/lista?tipo=LCP
  - Palácio do Planalto consolidations (authentic compiled HTML), via live fetch
    or Wayback/CDX of official planalto.gov.br URLs only:
    http://www.planalto.gov.br/ccivil_03/

Does not use Jusbrasil or other commercial databases. No WAF bypass
(planalto Imperva challenge is treated as live-fetch failure → Wayback).
robots.txt: LexML disallows /busca/ (not used); /urn is allowed.
"""
from __future__ import annotations

import json
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af

CC = "br"
COUNTRY = "Brazil"
SOURCE_TYPE = "lexml_planalto"
LICENSE = (
    "Official Brazilian legislative texts (União / Palácio do Planalto / LexML / "
    "Senado Dados Abertos). Official texts of normative acts are not objects of "
    "copyright (Lei 9.610/1998 art. 8º, IV). The authentic text is the Diário "
    "Oficial da União / Planalto compilation. Not legal advice. Not Jusbrasil."
)
UA = DEFAULT_UA + " source=https://www.lexml.gov.br/"
SENADO = "https://legis.senado.leg.br/dadosabertos/legislacao/lista"
LEXML_URN = "https://www.lexml.gov.br/urn"
PLANALTO = "http://www.planalto.gov.br/ccivil_03"
WORKERS = 10
SLEEP = 0.25
log = logging.getLogger("br")

ART_BR = re.compile(
    r"(?im)^\s*((?:Art(?:igo)?\.?|ARTIGO|ART\.)\s+\d+[ºo°]?[A-Za-z]?"
    r"(?:\s*[-–]\s*[A-Z])?(?:\s*[-–]?\s*(?:A|B|C|D|E|F))?)\b"
)
ATO_PERIODS = (
    (1995, 1998), (1999, 2002), (2003, 2006), (2007, 2010),
    (2011, 2014), (2015, 2018), (2019, 2022), (2023, 2026),
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


def split_custom(pattern, text, law_id, source_url, date):
    if not text or len(text) < 40:
        return []
    matches = list(pattern.finditer(text))
    if len(matches) < 2:
        return []
    docs = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = text[start:end].strip()
        num = re.sub(r"\s+", " ", m.group(1)).strip()
        aid = re.sub(r"[^a-z0-9]+", "-", num.lower()).strip("-")
        heading = chunk.split("\n", 1)[0][:200]
        docs.append({
            "id": f"{law_id}-{aid}"[:180],
            "title": heading, "text": chunk, "date_filed": date,
            "document_number": num, "source_url": source_url, "record_type": "article",
            "article_number": num, "law_identifier": law_id,
            "metadata": {"text_extraction": {"source": "official", "backend": "collector"}},
        })
        if len(docs) >= 4000:
            break
    return docs


def parse_date_br(val: Optional[str]) -> Optional[str]:
    if not val:
        return None
    val = val.strip()
    iso = iso_date(val)
    if iso:
        return iso
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", val)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return None


def catalog_path(kind: str) -> Path:
    return ROOT / CC / "raw" / f"catalog_{kind}.jsonl"


def load_catalog(kind: str) -> list[dict]:
    p = catalog_path(kind)
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


def save_catalog(kind: str, items: list[dict]) -> None:
    atomic_write(catalog_path(kind), "".join(json.dumps(it, ensure_ascii=False) + "\n" for it in items))


def parse_lista_json(raw: bytes, kind: str) -> list[dict]:
    items = []
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        return items
    block = data.get("ListaDocumento") or data
    docs = ((block.get("documentos") or {}).get("documento")) if isinstance(block, dict) else None
    if isinstance(docs, dict):
        docs = [docs]
    for doc in docs or []:
        if not isinstance(doc, dict):
            continue
        rec = {"kind": kind, "senado_id": str(doc.get("id") or "")}
        for k, v in doc.items():
            if k == "id":
                continue
            rec[k] = v if not isinstance(v, str) else v.strip()
        if rec.get("numero"):
            items.append(rec)
    return items


def parse_lista_xml(raw: bytes, kind: str) -> list[dict]:
    if raw[:1] in (b"{", b"[") or raw.lstrip()[:1] in (b"{", b"["):
        items = parse_lista_json(raw, kind)
        if items:
            return items
    items = []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        log.warning("lista XML parse fail kind=%s head=%s", kind, raw[:80])
        return parse_lista_json(raw, kind)
    for doc in root.iter():
        if localtag(doc.tag) != "documento":
            continue
        rec = {"kind": kind, "senado_id": doc.attrib.get("id")}
        for child in list(doc):
            rec[localtag(child.tag)] = (child.text or "").strip()
        if rec.get("numero"):
            items.append(rec)
    return items


def discover_kind(kind: str) -> list[dict]:
    existing = load_catalog(kind)
    min_n = 200 if kind == "LCP" else 10000
    if existing and len(existing) >= min_n:
        log.info("resume catalog %s n=%s", kind, len(existing))
        return existing
    url = f"{SENADO}?tipo={kind}"
    log.info("fetch senate catalog %s", url)
    r = http_get(
        url, ua=UA, sleep=0.2, timeout=(20, 180), retries=5,
        headers={"Accept": "application/xml, text/xml, application/json, */*"},
    )
    if r.status_code != 200 or not r.content:
        raise RuntimeError(f"senate catalog HTTP {r.status_code} {kind}")
    dest = ROOT / CC / "raw" / f"lista_{kind}.xml"
    dest.write_bytes(r.content)
    items = parse_lista_xml(r.content, kind)
    save_catalog(kind, items)
    log.info("catalog %s n=%s", kind, len(items))
    return items


def ato_folder(year: int) -> Optional[str]:
    for a, b in ATO_PERIODS:
        if a <= year <= b:
            return f"_Ato{a}-{b}"
    return None


def planalto_urls(kind: str, numero: str, year: Optional[int], date: Optional[str]) -> list[str]:
    urls: list[str] = []
    try:
        n = int(str(numero).lstrip("0") or "0")
    except Exception:
        n = 0
    if kind in {"CF", "constituicao"}:
        return [
            f"{PLANALTO}/constituicao/constituicao.htm",
            f"{PLANALTO}/Constituicao/Constituicao.htm",
            "https://www.planalto.gov.br/ccivil_03/constituicao/constituicao.htm",
        ]
    if kind == "LCP":
        urls += [
            f"{PLANALTO}/leis/lcp/lcp{n}.htm",
            f"{PLANALTO}/leis/lcp/Lcp{n}.htm",
            f"{PLANALTO}/leis/lcp/LCP{n}.htm",
        ]
        if year and year >= 2003:
            folder = ato_folder(year)
            if folder:
                urls.append(f"{PLANALTO}/{folder}/{year}/Lcp/Lcp{n}.htm")
                urls.append(f"{PLANALTO}/{folder}/{year}/lcp/Lcp{n}.htm")
    else:
        urls += [
            f"{PLANALTO}/leis/L{n}.htm",
            f"{PLANALTO}/leis/l{n}.htm",
            f"{PLANALTO}/leis/L{n:04d}.htm",
            f"{PLANALTO}/LEIS/L{n}.htm",
        ]
        if year and year >= 2003:
            folder = ato_folder(year)
            if folder:
                urls.append(f"{PLANALTO}/{folder}/{year}/Lei/L{n}.htm")
                urls.append(f"{PLANALTO}/{folder}/{year}/lei/L{n}.htm")
    # https twins
    extra = []
    for u in urls:
        extra.append(u.replace("http://", "https://"))
    out = []
    seen = set()
    for u in urls + extra:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def urn_for(it: dict) -> str:
    kind = it.get("kind") or "LEI"
    numero = it.get("numero") or ""
    date = parse_date_br(it.get("dataassinatura"))
    if kind == "CF":
        return "urn:lex:br:federal:constituicao:1988-10-05;1988"
    tipo = "lei.complementar" if kind == "LCP" else "lei"
    if date:
        return f"urn:lex:br:federal:{tipo}:{date};{numero}"
    year = it.get("anoassinatura") or (date or "")[:4]
    return f"urn:lex:br:federal:{tipo}:{year};{numero}"


def looks_like_law(text: str) -> bool:
    if not text or len(text) < 120:
        return False
    if af.is_challenge(text, 200) or af.is_spa_shell(text, html_to_text(text) if "<" in text[:200] else text):
        return False
    low = text.lower()
    if "bobcmn" in low or "tspd_" in low or "verificação de segurança" in low:
        return False
    hits = len(re.findall(r"(?i)\b(?:art(?:igo)?\.?|lei nº|lei n°|capítulo|capitulo)\b", text))
    return hits >= 1 or len(text) > 800


def fetch_body(url: str) -> tuple[str, str, str]:
    """Return (text, final_url, method)."""
    try:
        r = http_get(url, ua=UA, sleep=SLEEP, timeout=(20, 90), retries=3)
    except Exception:
        r = None
    html = ""
    if r is not None and r.status_code == 200 and r.content:
        ctype = (r.headers.get("content-type") or "").lower()
        if "html" in ctype or r.content[:1] in (b"<", b"\xef"):
            html = r.content.decode(r.encoding or "utf-8", "replace")
        if html and not af.is_challenge(html, r.status_code) and looks_like_law(html_to_text(html) or html):
            return html_to_text(html), r.url or url, "live"
    wb = af.get_wayback_content(url)
    if wb.get("status") == "success":
        raw = wb.get("text") or ""
        if (wb.get("content") or b"")[:4] == b"%PDF":
            return "", wb.get("wayback_url") or url, "pdf_skip"
        text = html_to_text(raw) if raw else ""
        if looks_like_law(text):
            return text, wb.get("wayback_url") or url, "wayback"
    return "", url, "fail"


def camara_from_urn_html(html: str) -> list[str]:
    urls = []
    for href in re.findall(r'href="([^"]+)"', html):
        href = href.replace("&amp;", "&")
        if "camara" in href and ("norma" in href or "publicacao" in href or "legin/fed" in href):
            urls.append(href)
        if "legis.senado.leg.br/norma/" in href and "publicacao" in href:
            urls.append(href)
    return urls


def fetch_one(it: dict, done: set[str]) -> str:
    kind = it.get("kind") or "LEI"
    numero = it.get("numero") or ""
    date = parse_date_br(it.get("dataassinatura"))
    year = None
    try:
        year = int(it.get("anoassinatura") or (date or "0")[:4] or 0) or None
    except Exception:
        year = None
    ident = f"br-{kind.lower()}-{numero}-{date or year or 'nd'}"
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    title = it.get("normaNome") or it.get("ementa") or ident
    urn = urn_for(it)
    source_url = f"{LEXML_URN}/{urn}"
    text = ""
    method = ""
    used = ""
    # 1) One best Planalto URL via Wayback first (live planalto is WAF-blocked).
    cands = planalto_urls(kind, numero, year, date)
    prefer = []
    for u in cands:
        if year and year >= 2003 and "_Ato" in u and u.startswith("http://"):
            prefer.append(u)
        elif (not year or year < 2003) and "/leis/L" in u and u.startswith("http://"):
            prefer.append(u)
        elif kind == "LCP" and "/lcp/" in u.lower() and u.startswith("http://"):
            prefer.append(u)
        elif kind == "CF" and u.startswith("http://"):
            prefer.append(u)
    ordered = (prefer or cands)[:2]
    for url in ordered:
        wb = af.get_wayback_content(url)
        if wb.get("status") == "success" and wb.get("text"):
            tx = html_to_text(wb["text"])
            if looks_like_law(tx):
                text, used, method = tx, wb.get("wayback_url") or url, "planalto_wayback"
                source_url = url
                break
        t2, final, meth = fetch_body(url)
        if t2 and looks_like_law(t2):
            text, used, method = t2, final, f"planalto_{meth}"
            source_url = url
            break
    # 2) LexML URN page → Câmara / Senado publication HTML (official)
    if not text:
        try:
            r = http_get(f"{LEXML_URN}/{urn}", ua=UA, sleep=SLEEP, timeout=(20, 90), retries=3)
        except Exception:
            r = None
        if r is not None and r.status_code == 200 and r.content:
            html = r.content.decode(r.encoding or "utf-8", "replace")
            if not af.is_challenge(html, 200):
                for href in camara_from_urn_html(html):
                    t, final, meth = fetch_body(href)
                    if t and looks_like_law(t):
                        text, used, method = t, final, f"lexml_link_{meth}"
                        source_url = href
                        break
    # 3) ementa-only last resort (still an official catalog row)
    if not text or len(text) < 80:
        ementa = it.get("ementa") or ""
        if len(ementa) >= 40:
            text = (
                f"{title}\n\n{ementa}\n\n"
                f"[Full compiled text not retrieved; official URN {urn}]"
            )
            method = "ementa_only"
            used = source_url
        else:
            log_failure(CC, {"id": rid, "url": source_url, "status": "failed", "reason": "empty_text"})
            return "fail"
    docs = split_custom(ART_BR, text, rid, used or source_url, date)
    if not docs:
        docs = split_articles(text, rid, used or source_url, date)
    repealed = bool(re.search(r"(?i)\brevogad", text[:2000] or ""))
    rec = base_record(
        cc=CC, country=COUNTRY, language="pt", ident=ident, title=title, text=text,
        source_url=used or source_url, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="collect_lexml.py", eli=f"{LEXML_URN}/{urn}", date=date,
        official_identifier=it.get("norma") or f"{kind} {numero}",
        document_type="constitution" if kind == "CF" else ("statute"),
        law_status="repealed" if repealed else "current",
        is_current=not repealed, documents=docs,
        extra_meta={
            "discovery": {"method": "senado_dadosabertos_lista", "kind": kind, "senado_id": it.get("senado_id")},
            "urn": urn,
            "ementa": it.get("ementa"),
            "text_extraction": {"source": "official", "backend": method},
        },
        extra_fields={"canonical_law_url": f"{LEXML_URN}/{urn}", "information_url": f"{LEXML_URN}/{urn}"},
    )
    rec["id"] = rid
    write_instrument(CC, rec)
    done.add(rid)
    return "ok"


def constitution_item() -> dict:
    return {
        "kind": "CF",
        "numero": "1988",
        "norma": "CF-1988",
        "normaNome": "Constituição da República Federativa do Brasil de 1988",
        "ementa": "Constituição da República Federativa do Brasil.",
        "dataassinatura": "05/10/1988",
        "anoassinatura": "1988",
        "senado_id": "cf-1988",
    }


def main():
    setup()
    t0 = utcnow()
    cf = [constitution_item()]
    leis = discover_kind("LEI")
    lcp = discover_kind("LCP")
    items = cf + leis + lcp
    counters = {"ok": 0, "skip": 0, "fail": 0}
    source_urls = [
        "https://www.lexml.gov.br/",
        "https://www.lexml.gov.br/urn/",
        "https://legis.senado.leg.br/dadosabertos/legislacao/lista?tipo=LEI",
        "http://www.planalto.gov.br/ccivil_03/",
        "https://www.planalto.gov.br/ccivil_03/constituicao/constituicao.htm",
    ]
    notes = (
        "Constituição 1988 plus numbered leis ordinárias and leis complementares "
        "from Senado Dados Abertos (lista XML). Full text prefers Palácio do Planalto "
        "compiled HTML (live, else Wayback of official planalto.gov.br URLs). LexML "
        "/urn used to resolve Câmara/Senado official HTML when Planalto is WAF-blocked. "
        "Not Jusbrasil. In-force status is not a Senate list filter; repealed language "
        "in the retrieved text is recorded as law_status=repealed."
    )

    def write_progress(coverage: str, extra: str = ""):
        write_summary(
            CC, country=COUNTRY,
            source="LexML Brasil / Palácio do Planalto / Senado Dados Abertos",
            source_urls=source_urls, license_text=LICENSE,
            discovered=len(items), fetched=counters["ok"], skipped=counters["skip"],
            failed=counters["fail"], coverage=coverage, notes=notes + extra,
        )

    done = existing_ids(CC)
    # Constitution first so a short run still has CF.
    log.info("constitution + leis=%s lcp=%s done=%s", len(leis), len(lcp), len(done))
    try:
        st = fetch_one(cf[0], done)
        counters[st] = counters.get(st, 0) + 1
        log.info("constitution %s", st)
    except Exception as exc:
        counters["fail"] += 1
        log_failure(CC, {"id": "br-cf", "status": "failed", "reason": repr(exc)})
    rest = leis + lcp
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
            counters[st] = counters.get(st, 0) + 1
            if n % 50 == 0 or n == len(rest):
                log.info("progress %s/%s ok=%s skip=%s fail=%s", n, len(rest), counters["ok"], counters["skip"], counters["fail"])
                write_progress("catalog-backed incomplete")
    cov = "full" if counters["fail"] == 0 and counters["ok"] + counters["skip"] >= len(items) else "catalog-backed incomplete"
    write_progress(cov, extra=f" Started {t0}.")
    log.info("done ok=%s skip=%s fail=%s coverage=%s", counters["ok"], counters["skip"], counters["fail"], cov)


if __name__ == "__main__":
    main()
