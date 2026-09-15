#!/usr/bin/env python3
"""Norway: Grunnloven + in-force lover from official Lovdata public data.

Official sources only (no commercial key, no Lovdata Pro, no Gyldendal/Karnov):
  https://api.lovdata.no/v1/publicData/list
  https://api.lovdata.no/v1/publicData/get/gjeldende-lover.tar.bz2
  Norsk Lovtidend Avdeling I packages on the same public endpoint
  Canonical HTML: https://lovdata.no/dokument/NL/...  (not crawled: robots
  User-agent * Disallow: /). data.lovdata.no does not resolve.

Public datasets are NLOD 2.0. Norsk Lovtidend is the authentic source and
prevails over consolidations (Lovdata publicData docs). Not legal advice.

On HTTP 429/403 of official URLs, archive_fallbacks.py of those URLs only.
"""
from __future__ import annotations

import json
import logging
import re
import sys
import tarfile
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af

CC = "no"
COUNTRY = "Norway"
SOURCE_TYPE = "lovdata"
LICENSE = (
    "Official Norwegian legislative texts (Lovdata / Norsk Lovtidend, "
    "Stiftelsen Lovdata on behalf of Justis- og beredskapsdepartementet). "
    "Public gjeldende-lover dataset under NLOD 2.0 "
    "(https://data.norge.no/nlod/no/2.0). Norsk Lovtidend prevails over "
    "consolidations. Not legal advice."
)
UA = DEFAULT_UA + " source=https://api.lovdata.no/ source=https://lovdata.no/"
API = "https://api.lovdata.no"
LIST_URL = API + "/v1/publicData/list"
GET_URL = API + "/v1/publicData/get/{filename}"
LAWS_PKG = "gjeldende-lover.tar.bz2"
FORSKRIFT_PKG = "gjeldende-sentrale-forskrifter.tar.bz2"
# skip forskrifter above this XML count (not tractable in this pass)
FORSKRIFT_MAX_XML = 8000
CONST_REF = "lov/1814-05-17"
log = logging.getLogger("no")

SKIP_BODY_TAGS = {
    "head", "script", "style", "noscript", "svg", "nav", "footer", "header",
}


def setup():
    ensure_dirs(CC)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def _dd_text(el: ET.Element) -> str:
    parts = []

    def walk(e: ET.Element) -> None:
        if e.text and e.text.strip():
            parts.append(e.text.strip())
        for c in list(e):
            walk(c)
            if c.tail and c.tail.strip():
                parts.append(c.tail.strip())

    walk(el)
    t = " ".join(parts)
    t = re.sub(r"[ \t]+", " ", t)
    return t.strip()


def parse_header(root: ET.Element) -> dict:
    meta: dict[str, str] = {}
    for dl in root.iter("dl"):
        kids = list(dl)
        i = 0
        while i < len(kids):
            el = kids[i]
            if localtag(el.tag) == "dt" and i + 1 < len(kids) and localtag(kids[i + 1].tag) == "dd":
                key = (el.get("class") or localtag(el.tag) or "").strip()
                meta[key] = _dd_text(kids[i + 1])
                i += 2
                continue
            i += 1
    if root.get("lang"):
        meta["lang"] = root.get("lang")
    return meta


def body_element(root: ET.Element) -> Optional[ET.Element]:
    for el in root.iter():
        if localtag(el.tag) == "main" and (el.get("id") == "dokument" or "documentBody" in (el.get("class") or "")):
            return el
    for el in root.iter():
        if el.get("id") == "dokument":
            return el
    return None


def element_to_text(el: ET.Element) -> str:
    parts: list[str] = []

    def walk(e: ET.Element) -> None:
        tag = localtag(e.tag).lower()
        if tag in SKIP_BODY_TAGS:
            return
        cls = e.get("class") or ""
        if tag in {"h1", "h2", "h3", "h4", "p", "br", "li", "tr", "div", "section"}:
            parts.append("\n")
        if tag == "article" and "legalArticle" in cls:
            parts.append("\n")
        if e.text and e.text.strip():
            parts.append(e.text.strip())
        for c in list(e):
            walk(c)
            if c.tail and c.tail.strip():
                parts.append(c.tail.strip())
        if tag in {"p", "h1", "h2", "h3", "h4", "article", "section", "li"}:
            parts.append("\n")

    walk(el)
    t = " ".join(parts)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r" *\n *", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def extract_articles(root: ET.Element, law_id: str, source_url: str, date: Optional[str]) -> list[dict]:
    docs = []
    seen = set()
    for el in root.iter("article"):
        cls = el.get("class") or ""
        if cls != "legalArticle" and "legalArticle" not in cls.split():
            continue
        if "legalArticleHeader" in cls:
            continue
        name = (el.get("data-name") or "").strip() or None
        url = el.get("data-lovdata-URL") or el.get("data-lovdata-url") or ""
        text = element_to_text(el)
        if not text or len(text) < 8:
            continue
        heading = text.split("\n", 1)[0][:200]
        num = name or heading[:40]
        aid = re.sub(r"[^a-z0-9]+", "-", num.lower()).strip("-") or f"art-{len(docs)+1}"
        if aid in seen:
            aid = f"{aid}-{len(docs)+1}"
        seen.add(aid)
        docs.append({
            "id": f"{law_id}-{aid}"[:180],
            "title": heading,
            "text": text,
            "date_filed": date,
            "document_number": num,
            "source_url": f"https://lovdata.no/dokument/{url}" if url else source_url,
            "record_type": "article",
            "article_number": num,
            "law_identifier": law_id,
            "metadata": {"text_extraction": {"source": "official", "backend": "lovdata-legalArticle"}},
        })
        if len(docs) >= 4000:
            break
    return docs


def parse_doc(raw: str, filename: str) -> Optional[dict]:
    xml = re.sub(r"<!DOCTYPE[^>]*>", "", raw, count=1).strip()
    if not xml.startswith("<"):
        return None
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return None
    meta = parse_header(root)
    lang = (root.get("lang") or meta.get("lang") or "nb").lower()
    lang = re.split(r"[^a-z-]+", lang, maxsplit=1)[0][:8]
    if lang in ("nb-no", "no-nb", "no"):
        lang = "nb"
    elif lang in ("nn-no", "no-nn"):
        lang = "nn"
    elif lang not in ("nb", "nn", "en", "se", "smj", "sma", "fkv"):
        lang = "nb"
    dokid = (meta.get("dokid") or "").strip()
    refid = (meta.get("refid") or "").strip()
    legacy = (meta.get("legacyID") or "").strip()
    title = (meta.get("title") or "").strip()
    if not title:
        for el in root.iter("title"):
            title = "".join(el.itertext()).strip()
            if title:
                break
    body = body_element(root)
    text = element_to_text(body) if body is not None else html_to_text(raw)
    if not text or len(text) < 40:
        text = html_to_text(raw)
    if not text or len(text) < 40:
        return None
    if not dokid:
        # filename nl-YYYYMMDD-NNN[-nn].xml
        m = re.search(r"nl-(\d{4})(\d{2})(\d{2})-(\d+)(?:-nn)?", filename)
        if m:
            n = int(m.group(4))
            dokid = f"NL/lov/{m.group(1)}-{m.group(2)}-{m.group(3)}" + (f"-{n}" if n else "")
    if not dokid:
        dokid = Path(filename).stem
    if filename.endswith("-nn.xml") and not dokid.endswith("/nn") and lang == "nn":
        ident = dokid + "-nn"
    else:
        ident = dokid
    date = iso_date(meta.get("dateOfPublication") or meta.get("dateInForce") or "")
    if not date:
        m = re.search(r"(1[6-9]\d{2}|20\d{2})-(\d{2})-(\d{2})", dokid or legacy or "")
        if m:
            date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    is_const = (refid == CONST_REF) or (dokid or "").endswith("lov/1814-05-17") or (
        "1814-05-17" in (dokid or "") and "/lov/" in (dokid or "")
    )
    is_forskrift = (
        (dokid or "").upper().startswith("SF/")
        or (refid or "").startswith("forskrift/")
        or "/sf/" in filename.replace("\\", "/").lower()
        or filename.lower().startswith("sf/")
        or (legacy or "").upper().startswith("FOR-")
    )
    if is_const:
        kind = "constitution"
    elif is_forskrift:
        kind = "regulation"
    else:
        kind = "statute"
    source_url = f"https://lovdata.no/dokument/{dokid}"
    eli = f"https://lovdata.no/eli/{dokid.lower()}" if dokid else None
    return {
        "ident": ident,
        "dokid": dokid,
        "refid": refid or ident,
        "legacy": legacy,
        "title": title or ident,
        "title_short": meta.get("titleShort") or "",
        "text": text,
        "lang": lang,
        "date": date,
        "kind": kind,
        "source_url": source_url,
        "eli": eli,
        "meta": meta,
        "root": root,
        "filename": filename,
        "is_const": is_const,
    }


def official_get_bytes(url: str, *, retries: int = 4, min_bytes: int = 100) -> dict:
    """Live GET of an official URL; Wayback/CC of the same URL on 429/403."""
    import time as _t
    last = None
    headers = {"Accept": "application/json, application/x-bzip2, application/octet-stream, */*",
               "User-Agent": UA}
    for attempt in range(1, retries + 1):
        _t.sleep(0.35)
        try:
            r = get_session(UA).get(url, timeout=(20, 180), headers=headers, allow_redirects=True)
        except Exception as exc:
            last = exc
            log.info("live net %s: %s", url, type(exc).__name__)
            continue
        last = r
        if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
            _t.sleep(min(30, 2 ** attempt))
            if r.status_code == 429:
                break
            continue
        if r.status_code == 200 and r.content and len(r.content) >= min_bytes:
            if af.is_challenge(r.text if r.headers.get("content-type", "").startswith("text") else "", r.status_code):
                break
            return {"ok": True, "content": r.content, "method": "live", "status": 200, "final_url": r.url}
        if r.status_code in (404, 410):
            return {"ok": False, "error": f"http_{r.status_code}", "status": r.status_code}
        if r.status_code in (429, 403):
            break
    status = getattr(last, "status_code", None) if hasattr(last, "status_code") else None
    if status in (429, 403) or status is None:
        log.info("archive fallback for %s status=%s", url, status)
        res = af.get_wayback_content(url)
        if res.get("status") == "success" and res.get("content"):
            return {"ok": True, "content": res["content"], "method": "wayback",
                    "wayback_url": res.get("wayback_url")}
        res2 = af.fetch_with_fallbacks(url, try_http=False, try_archive_is=True)
        if res2.get("status") == "success" and res2.get("content"):
            return {"ok": True, "content": res2["content"], "method": res2.get("method") or "archive"}
        return {"ok": False, "error": (res2 or res or {}).get("error") or "archive_fail"}
    err = f"http_{status}" if status else str(last)[:160]
    return {"ok": False, "error": err}


def list_packages() -> list[dict]:
    dest = ROOT / CC / "raw" / "publicData_list.json"
    got = official_get_bytes(LIST_URL, min_bytes=20)
    if got.get("ok"):
        try:
            data = json.loads(got["content"].decode("utf-8"))
        except Exception:
            data = None
        if isinstance(data, list) and data:
            dest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return data
    if dest.exists():
        try:
            return json.loads(dest.read_text(encoding="utf-8"))
        except Exception:
            pass
    return [{"filename": LAWS_PKG, "description": "Gjeldende lover (fallback name only)"}]


def fetch_package(filename: str, expected_size: Optional[int] = None) -> tuple[Path, str]:
    dest = ROOT / CC / "raw" / filename
    if dest.exists() and dest.stat().st_size > 100_000:
        if expected_size is None or dest.stat().st_size == expected_size or dest.stat().st_size > expected_size * 0.9:
            log.info("reuse local %s bytes=%s", filename, dest.stat().st_size)
            return dest, "local"
    url = GET_URL.format(filename=filename)
    got = official_get_bytes(url, retries=5, min_bytes=1000)
    if not got.get("ok"):
        raise RuntimeError(f"package {filename} fail: {got.get('error')}")
    raw = got["content"]
    if not (raw.startswith(b"BZh") or raw[:2] == b"\x1f\x8b" or raw[:2] == b"PK"):
        # maybe HTML error wrapped
        raise RuntimeError(f"package {filename} not an archive (magic={raw[:12]!r} method={got.get('method')})")
    dest.write_bytes(raw)
    log.info("saved %s bytes=%s method=%s", filename, dest.stat().st_size, got.get("method"))
    return dest, got.get("method") or "live"


def iter_xml_members(archive: Path):
    with tarfile.open(archive, "r:bz2") as tf:
        for m in tf.getmembers():
            if not m.isfile() or not m.name.lower().endswith(".xml"):
                continue
            f = tf.extractfile(m)
            if f is None:
                continue
            raw = f.read()
            yield m.name, raw


def sort_law_names(names: list[str]) -> list[str]:
    def key(n: str):
        const = "18140517" in n
        nn = n.endswith("-nn.xml")
        return (0 if const else 1, 0 if not nn else 1, n)
    return sorted(names, key=key)


def write_one(parsed: dict, retrieval: str, package: str, done: set[str]) -> str:
    ident = parsed["ident"]
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    docs = extract_articles(parsed["root"], rid, parsed["source_url"], parsed["date"])
    if len(docs) < 2:
        docs = split_articles(parsed["text"], rid, parsed["source_url"], parsed["date"]) or docs
    rec = base_record(
        cc=CC, country=COUNTRY, language=parsed["lang"], ident=ident,
        title=parsed["title"], text=parsed["text"],
        source_url=parsed["source_url"], source_type=SOURCE_TYPE,
        license_text=LICENSE, collector="no-lovdata-public-data",
        eli=parsed["eli"], date=parsed["date"],
        official_identifier=parsed.get("legacy") or parsed.get("refid") or ident,
        document_type=parsed["kind"],
        law_status="current", is_current=True,
        documents=docs,
        extra_meta={
            "discovery": {"method": "publicData_package", "package": package, "filename": parsed["filename"]},
            "retrieval": {"method": retrieval, "package": package},
            "official_metadata": {
                k: parsed["meta"].get(k) for k in
                ("dokid", "refid", "legacyID", "titleShort", "ministry",
                 "dateInForce", "lastChangeInForce", "lastChangedBy",
                 "dateOfPublication", "legalArea")
                if parsed["meta"].get(k)
            },
        },
        extra_fields={
            "canonical_title": parsed["title"],
            "aliases": [parsed["title_short"]] if parsed.get("title_short") else [],
            "record_type": "constitution" if parsed["kind"] == "constitution" else "law",
        },
    )
    err = validate_record(rec)
    if err:
        log.warning("schema %s: %s", ident, err[:200])
    write_instrument(CC, rec)
    done.add(rid)
    append_catalog(CC, {
        "ident": ident, "dokid": parsed["dokid"], "title": parsed["title"],
        "lang": parsed["lang"], "kind": parsed["kind"], "filename": parsed["filename"],
        "package": package, "retrieval": retrieval, "source_url": parsed["source_url"],
        "articles": rec["article_count"],
    })
    return "ok"


def ingest_package(archive: Path, retrieval: str, package: str, done: set[str],
                   kind_filter: Optional[str] = None) -> tuple[int, int, int, int]:
    members = list(iter_xml_members(archive))
    names = [n for n, _ in members]
    order = sort_law_names(names) if package.startswith("gjeldende-lover") else sorted(names)
    by_name = {n: raw for n, raw in members}
    discovered = ok = skip = fail = 0
    for i, name in enumerate(order, 1):
        discovered += 1
        raw_b = by_name[name]
        try:
            raw = raw_b.decode("utf-8")
        except Exception:
            raw = raw_b.decode("latin-1", "replace")
        try:
            parsed = parse_doc(raw, name)
        except Exception as exc:
            log_failure(CC, {"identifier": name, "status": "failed", "reason": repr(exc), "package": package})
            fail += 1
            continue
        if not parsed:
            log_failure(CC, {"identifier": name, "status": "failed", "reason": "empty_or_unparsed", "package": package})
            fail += 1
            continue
        if kind_filter and parsed["kind"] != kind_filter and not parsed["is_const"]:
            # still ingest; filter unused for lover package
            pass
        try:
            st = write_one(parsed, retrieval, package, done)
        except Exception as exc:
            log_failure(CC, {"identifier": parsed.get("ident"), "status": "failed", "reason": repr(exc)})
            fail += 1
            continue
        ok += st == "ok"
        skip += st == "skip"
        fail += st == "fail"
        if i % 100 == 0 or parsed.get("is_const"):
            log.info("progress %s %s/%s ok=%s skip=%s fail=%s ident=%s",
                     package, i, len(order), ok, skip, fail, parsed["ident"])
    return discovered, ok, skip, fail


def main():
    setup()
    t0 = utcnow()
    done = existing_ids(CC)
    pkgs = list_packages()
    log.info("publicData packages %s", [p.get("filename") for p in pkgs])
    size_by = {p.get("filename"): int(p["sizeBytes"]) for p in pkgs if p.get("filename") and str(p.get("sizeBytes") or "").isdigit()}

    # --- lover (Grunnloven first, then remaining in-force statutes) ---
    laws_path, laws_method = fetch_package(LAWS_PKG, size_by.get(LAWS_PKG))
    d1, ok1, skip1, fail1 = ingest_package(laws_path, laws_method, LAWS_PKG, done)
    log.info("lover done disc=%s ok=%s skip=%s fail=%s", d1, ok1, skip1, fail1)

    # --- forskrifter only if the zip is tractable after lover ---
    d2 = ok2 = skip2 = fail2 = 0
    forskrift_note = "forskrifter skipped"
    try:
        fpath, fmethod = fetch_package(FORSKRIFT_PKG, size_by.get(FORSKRIFT_PKG))
        with tarfile.open(fpath, "r:bz2") as tf:
            n_xml = sum(1 for m in tf.getmembers() if m.isfile() and m.name.lower().endswith(".xml"))
        log.info("forskrifter xml members=%s", n_xml)
        if n_xml <= FORSKRIFT_MAX_XML:
            d2, ok2, skip2, fail2 = ingest_package(fpath, fmethod, FORSKRIFT_PKG, done)
            forskrift_note = f"in-force sentrale forskrifter ingested xml={n_xml}"
        else:
            forskrift_note = f"forskrifter not ingested (xml={n_xml} > {FORSKRIFT_MAX_XML})"
            log.info(forskrift_note)
    except Exception as exc:
        forskrift_note = f"forskrifter not ingested: {exc}"
        log.warning(forskrift_note)

    discovered = d1 + d2
    ok = ok1 + ok2
    skip = skip1 + skip2
    fail = fail1 + fail2
    n_json = len(list((ROOT / CC / "instruments").glob("*.json")))
    coverage = "full" if fail == 0 and n_json >= 700 else "catalog-backed incomplete"
    notes = (
        "Grunnloven (bokmål + nynorsk) first, then remaining in-force Norges Lover "
        f"from {LAWS_PKG} (Lovdata public data, no API key). "
        "lovdata.no/dokument/NL is not HTML-crawled (robots User-agent * Disallow: /). "
        f"{forskrift_note}. "
        "Norsk Lovtidend Avdeling I gazette dumps listed on the same API are promulgations, "
        "not consolidations; not ingested in this statutes pass. "
        "Not Gyldendal Rett, not Karnov, not Lovdata Pro."
    )
    write_summary(
        CC, country=COUNTRY,
        source="Lovdata public data / Norges Lover (gjeldende lover) + Norsk Lovtidend",
        source_urls=[
            LIST_URL,
            GET_URL.format(filename=LAWS_PKG),
            "https://lovdata.no/info/api",
            "https://api.lovdata.no/publicData",
            "https://lovdata.no/dokument/NL",
        ],
        license_text=LICENSE, discovered=discovered, fetched=ok, skipped=skip, failed=fail,
        coverage=coverage, notes=notes, last_run=utcnow(),
        extra=f"started {t0}; lover_method={laws_method}; instruments_now={n_json}",
    )
    log.info("done disc=%s ok=%s skip=%s fail=%s instruments=%s", discovered, ok, skip, fail, n_json)


if __name__ == "__main__":
    main()
