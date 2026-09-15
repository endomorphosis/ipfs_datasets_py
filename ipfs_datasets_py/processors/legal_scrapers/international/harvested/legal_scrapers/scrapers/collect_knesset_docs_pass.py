#!/usr/bin/env python3
"""Second pass: Reshumot / נוסח חדש PDFs from KNS_DocumentLaw (laws as enacted)."""
from __future__ import annotations
import json, logging, sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect_knesset_laws import *
from collect_knesset_laws import dump_jsonl, load_jsonl, odata_get, ODATA_V2

log = logging.getLogger("il-docs")
WANT = {9, 97, 125, 113}


def knesset_law_titles(ids: set) -> dict:
    dest = ROOT / CC / "raw" / "KNS_Law_titles.json"
    cached = {}
    if dest.exists():
        try:
            cached = json.loads(dest.read_text(encoding="utf-8"))
        except Exception:
            cached = {}
    missing = [i for i in ids if str(i) not in cached]
    log.info("title lookup missing=%s cached=%s", len(missing), len(cached))
    # batch via skip of KNS_Law is huge; fetch by id in modest workers
    def one(i):
        try:
            data = odata_get(f"{ODATA_V2}/KNS_Law", {"$format":"json","$top":1,"$filter":f"LawID eq {int(i)}"})
            vals = data.get("value") or []
            return i, vals[0] if vals else None
        except Exception as exc:
            return i, None
    with ThreadPoolExecutor(max_workers=4) as ex:
        n=0
        futs=[ex.submit(one, i) for i in missing]
        for fut in as_completed(futs):
            i, rec = fut.result()
            cached[str(i)] = rec
            n+=1
            if n % 50 == 0:
                log.info("titles %s/%s", n, len(missing))
    dest.write_text(json.dumps(cached, ensure_ascii=False), encoding="utf-8")
    return cached


def main():
    setup()
    docs = load_jsonl(ROOT / CC / "raw" / "KNS_DocumentLaw.jsonl")
    names = load_jsonl(ROOT / CC / "raw" / "KNS_IsraelLawName.jsonl")
    binds = load_jsonl(ROOT / CC / "raw" / "KNS_LawBinding.jsonl")
    laws = load_jsonl(ROOT / CC / "raw" / "KNS_IsraelLaw.jsonl")
    law_by_id = {x["Id"]: x for x in laws}
    il_by_lawid = defaultdict(list)
    for n in names:
        if n.get("LawID") is not None:
            il_by_lawid[n["LawID"]].append(n.get("IsraelLawID"))
    for b in binds:
        if b.get("LawID") is not None:
            il_by_lawid[b["LawID"]].append(b.get("IsraelLawID"))
    by = defaultdict(list)
    for d in docs:
        if d.get("GroupTypeID") not in WANT:
            continue
        path = (d.get("FilePath") or "")
        app = (d.get("ApplicationDesc") or "").upper()
        if not (path.lower().endswith(".pdf") or app == "PDF"):
            continue
        by[d.get("LawID")].append(d)
    log.info("primary pdf law ids %s", len(by))
    titles = {}
    # skip per-id KNS_Law lookups; titles from IsraelLaw join when present
    done = existing_ids(CC)
    # skip if this IsraelLaw already stored
    have_il = set()
    for p in (ROOT / CC / "instruments").glob("*.json"):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        ident = rec.get("official_identifier") or rec.get("identifier") or ""
        if str(ident).isdigit():
            have_il.add(int(ident))
    items = []
    for lid, cands in by.items():
        ils = [i for i in il_by_lawid.get(lid, []) if i]
        if any(i in have_il for i in ils):
            continue
        ident = f"reshumot-{lid}"
        if slug_id(CC, ident) in done:
            continue
        items.append((lid, cands, ils))
    log.info("to fetch %s", len(items))
    ok=skip=fail=0
    def fetch(item):
        lid, cands, ils = item
        ident = f"reshumot-{lid}"
        rid = slug_id(CC, ident)
        picked = [d for d in sorted(cands, key=rank_doc) if (d.get("FilePath") or "").lower().endswith(".pdf") or (d.get("ApplicationDesc") or "").upper()=="PDF"][:2]
        texts, used = [], None
        for d in picked:
            raw = fetch_pdf(d.get("FilePath") or "")
            if not raw:
                continue
            t = pdf_to_text(raw)
            if len(t) < 80:
                continue
            texts.append(f"{d.get('GroupTypeDesc') or 'document'}\n\n{t}")
            used = d.get("FilePath")
            if d.get("GroupTypeID")==97 and len(t)>400:
                break
        text="\n\n".join(texts).strip()
        if len(text)<80:
            log_failure(CC, {"identifier": ident, "status":"failed", "reason":"empty_pdf_text"})
            return "fail"
        meta = titles.get(str(lid)) or {}
        title = meta.get("Name") or ident
        ilaw = None
        for i in ils:
            if i in law_by_id:
                ilaw = law_by_id[i]
                break
        if ilaw:
            title = ilaw.get("Name") or title
            st, is_cur = status_of(ilaw)
            date = iso_date((ilaw.get("PublicationDate") or "")[:10])
        else:
            st, is_cur = "unknown", None
            date = iso_date((meta.get("PublicationDate") or "")[:10]) if meta else None
        rec = base_record(
            cc=CC, country=COUNTRY, language="he", ident=ident, title=title, text=text,
            source_url=used, source_type=SOURCE_TYPE, license_text=LICENSE, collector="il-knesset",
            date=date, official_identifier=str(lid), document_type="statute",
            law_status=st, is_current=is_cur, documents=split_he(text, rid, used, date),
            extra_meta={"discovery": {"method": "knesset_documentlaw_reshumot", "law_id": lid, "israel_law_ids": ils},
                        "text_extraction": {"source": "official", "backend": "knesset-fs-pdf"}},
        )
        write_instrument(CC, rec)
        return "ok"
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs=[ex.submit(fetch, it) for it in items]
        n=0
        for fut in as_completed(futs):
            n+=1
            try:
                st=fut.result()
            except Exception as exc:
                st="fail"
                log_failure(CC, {"status":"failed","reason":repr(exc)})
            ok += st=="ok"; skip += st=="skip"; fail += st=="fail"
            if n % 40 == 0 or n==len(items):
                log.info("docs-pass %s/%s ok=%s fail=%s", n, len(items), ok, fail)
    log.info("docs-pass done ok=%s fail=%s", ok, fail)
    write_summary(CC, country=COUNTRY, source="Knesset OData + Reshumot PDFs (fs.knesset.gov.il)",
                  source_urls=["https://knesset.gov.il/OdataV4/ParliamentInfo/",
                               "https://knesset.gov.il/Odata/ParliamentInfo.svc/",
                               "https://main.knesset.gov.il/Activity/Legislation/Laws/Pages/LawReshumot.aspx"],
                  license_text=LICENSE, discovered=len(items)+111, fetched=ok, skipped=skip, failed=fail,
                  coverage="in-force-plus-reshumot snapshot",
                  notes="In-force IsraelLaw with joinable PDFs plus additional Reshumot/נוסח חדש PDFs as enacted. LawHome WAF-blocked. Not Nevo/Takdin.",
                  last_run=utcnow())

if __name__ == "__main__":
    main()
