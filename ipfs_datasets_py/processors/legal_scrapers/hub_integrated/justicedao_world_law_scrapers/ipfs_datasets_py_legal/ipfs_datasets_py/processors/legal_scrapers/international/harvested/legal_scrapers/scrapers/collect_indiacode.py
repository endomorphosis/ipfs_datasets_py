#!/usr/bin/env python3
"""India: Central Acts in force from India Code (Legislative Department).

Official source only:
  https://indiacode.gov.in/  (migrated from indiacode.nic.in)
  DSpace 7 discover/core API on the same host (Ministry of Law and Justice)

Central Acts (CENTRAL community) first. State acts, rules, notifications,
and the Repeal / Acts-Not-Enforced communities are out of scope.
Optional official Constitution PDFs (English + Hindi 2026 editions) from
the Constitution of India community on the same host.

Does NOT use eCourtsIndia, Parse.bot, Manupatra, SCC, or Westlaw.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *

CC = "in"
COUNTRY = "India"
SOURCE_TYPE = "indiacode"
LICENSE = (
    "Research snapshot of official India Code texts (Legislative Department, "
    "Ministry of Law and Justice). Reuse is governed by Government of India / "
    "India Code website terms (https://indiacode.gov.in/). This snapshot does "
    "not claim CC0. license: other. Not legal advice; the authentic gazette / "
    "India Code text prevails."
)
UA = DEFAULT_UA + " source=https://indiacode.gov.in/"
API = "https://indiacode.gov.in/server/api"
CENTRAL = "f467b316-98f0-4c08-a722-a2627e45bc19"
CONSTITUTION = "8897f9c9-e0bf-4369-8f49-ebd766018a78"
WORKERS = 4
SLEEP = 0.4
PAGE = 100
log = logging.getLogger("in")

HDRS = {
    "Accept": "application/json, application/hal+json, */*",
    "Accept-Language": "en,hi;q=0.8,*;q=0.5",
}


def setup():
    ensure_dirs(CC)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def md_val(md: dict, key: str, default: str = "") -> str:
    vals = md.get(key) or []
    if not vals:
        return default
    v = vals[0]
    if isinstance(v, dict):
        return (v.get("value") or default) or default
    return str(v) if v is not None else default


def md_all(md: dict, key: str) -> list[str]:
    out = []
    for v in md.get(key) or []:
        if isinstance(v, dict):
            s = v.get("value")
        else:
            s = v
        if s:
            out.append(str(s))
    return out


def unwrap_item(obj: dict) -> dict:
    if not obj:
        return {}
    if obj.get("type") == "discover" or "_embedded" in obj and "indexableObject" in (obj.get("_embedded") or {}):
        return (obj.get("_embedded") or {}).get("indexableObject") or obj
    return obj


def api_get(path: str, params: Optional[dict] = None) -> dict:
    url = path if path.startswith("http") else f"{API}{path}"
    r = http_get(url, ua=UA, sleep=SLEEP, headers=HDRS, params=params, retries=5)
    if r.status_code != 200 or not r.content:
        raise RuntimeError(f"HTTP {r.status_code} {url}")
    try:
        return r.json()
    except Exception as exc:
        raise RuntimeError(f"json fail {url}: {exc}") from exc


def search_page(scope: str, collection: Optional[str], page: int, size: int = PAGE) -> dict:
    params: dict[str, Any] = {
        "query": "*",
        "scope": scope,
        "dsoType": "ITEM",
        "page": page,
        "size": size,
    }
    if collection:
        params["f.identifier_collection"] = f"{collection},equals"
    return api_get("/discover/search/objects", params)


def search_result(data: dict) -> dict:
    return (data.get("_embedded") or {}).get("searchResult") or {}


def load_jsonl(path: Path) -> list[dict]:
    items = []
    if not path.exists() or path.stat().st_size < 20:
        return items
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except Exception:
                continue
    return items


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    atomic_write(path, body)


def compact_act(item: dict) -> dict:
    md = item.get("metadata") or {}
    handle = item.get("handle") or ""
    act_id = md_val(md, "dc.identifier.act_id") or handle
    return {
        "uuid": item.get("uuid") or item.get("id"),
        "handle": handle,
        "name": item.get("name") or md_val(md, "dc.title"),
        "act_id": act_id,
        "act_number": md_val(md, "dc.identifier.act_number"),
        "act_year": md_val(md, "dc.date.act_year"),
        "enact_date": md_val(md, "dc.date.enact_date") or md_val(md, "dc.date.issued"),
        "enforcement_date": md_val(md, "dc.date.enforcement_date"),
        "repealed": md_val(md, "dc.identifier.repealed").lower(),
        "ministry": md_val(md, "dc.identifier.ministry_name"),
        "department": md_val(md, "dc.identifier.department_name"),
        "state_name": md_val(md, "dc.identifier.state_name"),
        "long_title": md_val(md, "dc.title.long_title"),
        "regional_title": md_val(md, "dc.title.regional"),
        "preamble_html": md_val(md, "dc.identifier.preamble_description"),
        "preamble_title": md_val(md, "dc.identifier.preamble_title"),
        "no_of_section": md_val(md, "dc.identifier.no_of_section"),
        "givenid": md_val(md, "dc.identifier.givenid"),
    }


def compact_section(item: dict) -> dict:
    md = item.get("metadata") or {}
    return {
        "uuid": item.get("uuid") or item.get("id"),
        "handle": item.get("handle") or "",
        "name": item.get("name") or md_val(md, "dc.title"),
        "act_id": md_val(md, "dc.identifier.act_id"),
        "act_name": md_val(md, "dc.title.act_name"),
        "section_number": md_val(md, "dc.identifier.section_number"),
        "order_number": md_val(md, "dc.identifier.order_number"),
        "repealed": md_val(md, "dc.identifier.repealed").lower(),
        "act_repealed": md_val(md, "dc.identifier.act_repealed").lower(),
        "html": md_val(md, "dc.identifier.section_page_note"),
        "ministry": md_val(md, "dc.identifier.ministry_name"),
    }


def paginate_collection(scope: str, collection: str, compact_fn, dest: Path, label: str) -> list[dict]:
    existing = load_jsonl(dest)
    if existing:
        # verify page 0 still matches expected total; resume if complete
        try:
            probe = search_page(scope, collection, 0, size=1)
            sr = search_result(probe)
            total = int((sr.get("page") or {}).get("totalElements") or 0)
        except Exception as exc:
            log.warning("probe %s failed (%s); using cached %s", label, exc, len(existing))
            return existing
        if total and len(existing) >= total:
            log.info("resume %s catalog %s (total=%s)", label, len(existing), total)
            return existing
        log.info("%s catalog incomplete %s/%s; refetch", label, len(existing), total)
    def absorb(raw_objs, items, seen):
        n = 0
        for raw in raw_objs:
            it = compact_fn(unwrap_item(raw))
            key = it.get("uuid") or it.get("handle") or it.get("act_id")
            if not key or key in seen:
                continue
            seen.add(key)
            items.append(it)
            n += 1
        return n

    items: list[dict] = []
    seen = set()
    data = search_page(scope, collection, 0, size=PAGE)
    sr = search_result(data)
    pg = sr.get("page") or {}
    total_pages = min(int(pg.get("totalPages") or 1), 2000)
    objs = ((sr.get("_embedded") or {}).get("objects")) or []
    absorb(objs, items, seen)
    log.info("%s page=1/%s total=%s", label, total_pages, len(items))
    if total_pages > 1:
        def fetch_p(p):
            d = search_page(scope, collection, p, size=PAGE)
            srr = search_result(d)
            return p, ((srr.get("_embedded") or {}).get("objects")) or []
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futs = [ex.submit(fetch_p, p) for p in range(1, total_pages)]
            done_p = 1
            for fut in as_completed(futs):
                p, objs = fut.result()
                absorb(objs, items, seen)
                done_p += 1
                if done_p % 20 == 0 or done_p == total_pages:
                    log.info("%s pages=%s/%s items=%s", label, done_p, total_pages, len(items))
    write_jsonl(dest, items)
    return items


def order_key(sec: dict) -> tuple:
    try:
        o = int(re.sub(r"[^\d]", "", sec.get("order_number") or "") or "0")
    except Exception:
        o = 0
    try:
        n = int(re.sub(r"[^\d]", "", sec.get("section_number") or "") or "0")
    except Exception:
        n = 0
    return o, n, sec.get("section_number") or "", sec.get("name") or ""


def section_docs(secs: list[dict], law_id: str, source_url: str, date: Optional[str]) -> tuple[list[dict], str]:
    parts: list[str] = []
    docs: list[dict] = []
    seen = set()
    for sec in sorted(secs, key=order_key):
        html = sec.get("html") or ""
        body = html_to_text(html) if html else ""
        num = (sec.get("section_number") or "").strip()
        title = (sec.get("name") or "").strip()
        head = f"Section {num}. {title}".strip() if num else (title or "Section")
        chunk = head
        if body:
            chunk = f"{head}\n\n{body}".strip()
        if not chunk or len(chunk) < 8:
            continue
        parts.append(chunk)
        aid = re.sub(r"[^a-z0-9]+", "-", f"section-{num or title}".lower()).strip("-") or "section"
        doc_id = f"{law_id}-{aid}"[:180]
        if doc_id in seen:
            doc_id = f"{doc_id}-{sec.get('uuid','')[:8]}"[:180]
        seen.add(doc_id)
        docs.append({
            "id": doc_id,
            "title": head[:200],
            "text": chunk,
            "date_filed": date,
            "document_number": num or None,
            "source_url": f"https://indiacode.gov.in/handle/{sec['handle']}" if sec.get("handle") else source_url,
            "record_type": "article",
            "article_number": num or None,
            "law_identifier": law_id,
            "metadata": {
                "text_extraction": {"source": "official", "backend": "indiacode-dspace"},
                "section_uuid": sec.get("uuid"),
            },
        })
        if len(docs) >= 4000:
            break
    return docs, "\n\n".join(parts)


def pdf_to_text(raw: bytes) -> str:
    if not raw or raw[:4] != b"%PDF":
        return ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
            tmp.write(raw)
            tmp.flush()
            proc = subprocess.run(
                ["pdftotext", "-layout", "-enc", "UTF-8", tmp.name, "-"],
                check=False, capture_output=True, timeout=180,
            )
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout.decode("utf-8", "replace").strip()
    except Exception as exc:
        log.warning("pdftotext failed: %s", exc)
    return ""


def fetch_item_pdf_text(uuid: str) -> str:
    if not uuid:
        return ""
    try:
        data = api_get(f"/core/items/{uuid}/bundles")
    except Exception as exc:
        log.info("bundles fail %s: %s", uuid, exc)
        return ""
    for bun in ((data.get("_embedded") or {}).get("bundles")) or []:
        href = ((bun.get("_links") or {}).get("bitstreams") or {}).get("href")
        if not href:
            continue
        try:
            bs = api_get(href)
        except Exception:
            continue
        for bit in ((bs.get("_embedded") or {}).get("bitstreams")) or []:
            mime = (bit.get("mimeType") or bit.get("mimetype") or "").lower()
            name = (bit.get("name") or "").lower()
            content = ((bit.get("_links") or {}).get("content") or {}).get("href")
            if not content:
                continue
            if "pdf" not in mime and not name.endswith(".pdf"):
                continue
            r = http_get(
                content, ua=UA, sleep=SLEEP,
                headers={"Accept": "application/pdf,*/*"}, retries=3, timeout=(20, 120),
            )
            if r.status_code == 200 and r.content[:4] == b"%PDF":
                return pdf_to_text(r.content)
    return ""


def discover() -> tuple[list[dict], dict[str, list[dict]]]:
    acts = paginate_collection(
        CENTRAL, "ACT", compact_act, ROOT / CC / "raw" / "acts.jsonl", "acts",
    )
    secs = paginate_collection(
        CENTRAL, "SECTION", compact_section, ROOT / CC / "raw" / "sections.jsonl", "sections",
    )
    by_act: dict[str, list[dict]] = defaultdict(list)
    for sec in secs:
        aid = sec.get("act_id") or ""
        if aid:
            by_act[aid].append(sec)
    return acts, by_act


def write_act(act: dict, secs: list[dict], done: set[str]) -> str:
    act_id = act.get("act_id") or act.get("handle") or act.get("uuid")
    if not act_id:
        return "fail"
    rid = slug_id(CC, act_id)
    if rid in done:
        return "skip"
    handle = act.get("handle") or ""
    source_url = f"https://indiacode.gov.in/handle/{handle}" if handle else "https://indiacode.gov.in/"
    date = iso_date(act.get("enact_date") or act.get("enforcement_date") or act.get("act_year"))
    preamble = html_to_text(act.get("preamble_html") or "")
    docs, body = section_docs(secs, rid, source_url, date)
    chunks = []
    if preamble:
        ptitle = act.get("preamble_title") or "Preamble"
        chunks.append(f"{ptitle}\n\n{preamble}".strip())
    if body:
        chunks.append(body)
    text = "\n\n".join(chunks).strip()
    backend = "indiacode-dspace-html"
    if len(text) < 80:
        pdf_text = fetch_item_pdf_text(act.get("uuid") or "")
        if pdf_text:
            text = pdf_text
            backend = "indiacode-dspace-pdf"
            if not docs:
                docs = split_articles(text, rid, source_url, date)
    if len(text) < 40:
        log_failure(CC, {
            "identifier": act_id, "source_url": source_url,
            "status": "failed", "reason": "empty_text",
            "title": act.get("name"),
        })
        return "fail"
    repealed = (act.get("repealed") or "").lower() == "true"
    law_status = "repealed" if repealed else "current"
    title = act.get("name") or act_id
    year = act.get("act_year") or ""
    num = act.get("act_number") or ""
    official = title
    if num and year:
        official = f"Act {num} of {year}"
    elif act.get("givenid"):
        official = str(act.get("givenid"))
    languages = ["en"]
    extra_fields = {}
    if act.get("regional_title"):
        languages.append("hi")
        extra_fields["aliases"] = [act["regional_title"]]
    rec = base_record(
        cc=CC, country=COUNTRY, language="en", ident=act_id, title=title, text=text,
        source_url=source_url, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="in-indiacode", eli=None, date=date,
        official_identifier=official, document_type="statute",
        law_status=law_status, is_current=not repealed, documents=docs,
        extra_meta={
            "discovery": {
                "method": "dspace_discover",
                "community": "CENTRAL",
                "collection": "ACT",
                "uuid": act.get("uuid"),
                "handle": handle,
                "act_id": act_id,
            },
            "official_metadata": {
                k: act.get(k) for k in (
                    "act_number", "act_year", "ministry", "department",
                    "state_name", "long_title", "enforcement_date",
                    "no_of_section", "givenid",
                ) if act.get(k)
            },
            "languages": languages,
            "text_extraction": {"source": "official", "backend": backend},
        },
        extra_fields=extra_fields or None,
    )
    rec["languages"] = languages
    if act.get("long_title"):
        rec["canonical_title"] = act["long_title"]
    write_instrument(CC, rec)
    return "ok"


def add_constitution() -> tuple[int, int]:
    """Official EN/HI Constitution PDFs from the same India Code host."""
    done = existing_ids(CC)
    ok = fail = 0
    try:
        data = search_page(CONSTITUTION, None, 0, size=50)
    except Exception as exc:
        log.warning("constitution community: %s", exc)
        return 0, 0
    sr = search_result(data)
    objs = ((sr.get("_embedded") or {}).get("objects")) or []
    want = []
    for raw in objs:
        it = unwrap_item(raw)
        name = (it.get("name") or "").lower()
        if "english 2026" in name or name.endswith("in english 2026"):
            want.append(("en", it))
        elif "hindi 2026" in name:
            want.append(("hi", it))
    for lang, it in want:
        handle = it.get("handle") or ""
        ident = f"constitution-{lang}-2026"
        rid = slug_id(CC, ident)
        if rid in done:
            continue
        source_url = f"https://indiacode.gov.in/handle/{handle}" if handle else "https://indiacode.gov.in/"
        text = fetch_item_pdf_text(it.get("uuid") or "")
        if len(text) < 80:
            log_failure(CC, {
                "identifier": ident, "source_url": source_url,
                "status": "failed", "reason": "constitution_pdf_empty",
            })
            fail += 1
            continue
        docs = split_articles(text, rid, source_url, "2026-01-01")
        rec = base_record(
            cc=CC, country=COUNTRY, language=lang, ident=ident,
            title=it.get("name") or f"The Constitution of India ({lang})",
            text=text, source_url=source_url, source_type=SOURCE_TYPE,
            license_text=LICENSE, collector="in-indiacode",
            date="2026-01-01", official_identifier="Constitution of India",
            document_type="constitution", law_status="current", is_current=True,
            documents=docs,
            extra_meta={
                "discovery": {
                    "method": "dspace_constitution_community",
                    "uuid": it.get("uuid"),
                    "handle": handle,
                },
                "text_extraction": {"source": "official", "backend": "indiacode-dspace-pdf"},
            },
        )
        rec["languages"] = [lang]
        write_instrument(CC, rec)
        ok += 1
        log.info("constitution %s ok chars=%s", lang, len(text))
    return ok, fail


def main():
    setup()
    t0 = utcnow()
    acts, by_act = discover()
    log.info("discovered acts=%s section_groups=%s", len(acts), len(by_act))
    done = existing_ids(CC)
    ok = skip = fail = 0
    # in-force first
    acts_sorted = sorted(acts, key=lambda a: (a.get("repealed") == "true", a.get("name") or ""))
    n = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {
            ex.submit(write_act, act, by_act.get(act.get("act_id") or "", []), done): act
            for act in acts_sorted
        }
        for fut in as_completed(futs):
            n += 1
            try:
                st = fut.result()
            except Exception as exc:
                st = "fail"
                log_failure(CC, {"status": "failed", "reason": repr(exc)})
            ok += st == "ok"
            skip += st == "skip"
            fail += st == "fail"
            if n % 50 == 0 or n == len(acts_sorted):
                log.info("progress %s/%s ok=%s skip=%s fail=%s", n, len(acts_sorted), ok, skip, fail)
                write_summary(
                    CC, country=COUNTRY, source="India Code / Legislative Department",
                    source_urls=["https://indiacode.gov.in/"],
                    license_text=LICENSE, discovered=len(acts), fetched=ok,
                    skipped=skip, failed=fail, coverage="catalog-backed incomplete",
                    notes="Central Acts from India Code DSpace API", last_run=utcnow(),
                )
    cok, cfail = add_constitution()
    ok += cok
    fail += cfail
    coverage = "catalog-backed incomplete"
    if fail == 0 and ok + skip >= len(acts):
        coverage = "central-acts-in-force snapshot"
    notes = (
        "Central Acts (CENTRAL community, identifier_collection=ACT) from the "
        "official India Code DSpace API at indiacode.gov.in. Section HTML from "
        "SECTION items assembled per act_id. Constitution English and Hindi 2026 "
        "PDFs included when bitstreams extract. State acts, rules, notifications, "
        "Repeal community, and Acts Not Enforced are out of scope. Not eCourtsIndia "
        "/ Parse.bot / commercial DBs. Hindi titles recorded when India Code publishes "
        "dc.title.regional; section bodies are the official English HTML."
    )
    write_summary(
        CC, country=COUNTRY, source="India Code / Legislative Department / Ministry of Law and Justice",
        source_urls=[
            "https://indiacode.gov.in/",
            "https://indiacode.gov.in/server/api/discover/search/objects",
        ],
        license_text=LICENSE, discovered=len(acts), fetched=ok, skipped=skip, failed=fail,
        coverage=coverage, notes=notes, last_run=utcnow(), extra=f"started {t0}",
    )
    log.info("done ok=%s skip=%s fail=%s constitution_ok=%s", ok, skip, fail, cok)


if __name__ == "__main__":
    main()
