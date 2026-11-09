#!/usr/bin/env python3
"""Build ipfs_kenya_municipal_laws parquet (national laws/articles schema + municipality_id,
municipality_name, wikidata_qid) from /dev/shm/muni_africa/ke/records.jsonl. RAM staging only."""
import hashlib, json, os, re, sys
from pathlib import Path
import pyarrow as pa, pyarrow.parquet as pq

STAGE = Path(os.environ.get("MUNI_STAGE", "/dev/shm/muni_africa/ke"))
OUT = STAGE / "hf" / "ipfs_kenya_municipal_laws" / "data"
LICENSE = ("Kenya Law (National Council for Law Reporting) county legislation; the site describes its "
           "contents as public domain except material expressly marked with a Creative Commons licence "
           "(terms: https://new.kenyalaw.org/terms-of-use/).")

def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")

_CLEAN = re.compile(r"[a-z0-9]+(?:[-/][a-z0-9]+)*")
def law_id(w):
    """Injective over FRBR work: readable slug when lossless, else slug + short hash of the exact FRBR URI."""
    p = w.replace("/akn/", "")
    s = slug(p)
    if not _CLEAN.fullmatch(p):
        s += "-x" + hashlib.sha1(w.encode("utf-8")).hexdigest()[:10]
    return "ke-muni-" + s

recs = {}
for line in open(STAGE / "records.jsonl"):
    r = json.loads(line)
    recs[r["work"]] = r  # last wins
laws, arts = [], []
munis = set()
for w, r in recs.items():
    if r.get("page_status") != 200:
        continue
    lid = law_id(w)
    secs = r.get("sections") or []
    mcols = {"municipality_id": r["county_code"], "municipality_name": r["county_name"], "wikidata_qid": r.get("qid", "")}
    munis.add(r["county_code"])
    meta = {"schema_version": "collection_record.v1", "record_type": "law", "law_identifier": lid,
            "frbr_work": w, "citation": r.get("citation"), "display_type": r.get("display_type"),
            "pdf_url": r.get("pdf_url"), "pdf_bytes": r.get("pdf_bytes"), "commenced": r.get("commenced"),
            "text_backend": r.get("text_backend"), "no_text_layer": bool(r.get("no_text_layer")),
            "error": r.get("error"), "admin_level": "county", "publisher": "Kenya Law (NCLR)"}
    is_ln = "/act/ln/" in w
    laws.append({"id": lid, "title": r.get("title") or "", "text": r.get("text") or "",
                 "source_url": r["source_url"], "source_type": "kenyalaw_county_legislation",
                 "jurisdiction": "KE", "country": "Kenya", "language": "en",
                 "eli": w, "date": r.get("expression_date") or "", "date_issued": r.get("expression_date") or "",
                 "retrieved_at": r["retrieved_at"], "license": LICENSE, "law_status": "current",
                 "identifier": r.get("citation") or w, "official_identifier": w,
                 "article_count": len(secs), "json_path": "", "metadata_json": json.dumps(meta, ensure_ascii=False),
                 **mcols})
    for s in secs:
        num = str(s["num"])
        arts.append({"law_id": lid, "id": f"{lid}-s-{slug(num)}"[:200], "title": s["title"], "text": s["text"],
                     "source_url": r["source_url"], "document_number": f"section {num}",
                     "article_number": f"section {num}", "record_type": "article",
                     "metadata_json": json.dumps({"law_identifier": lid, "kind": "regulation" if is_ln else "section"}),
                     **mcols})
# uniqueness assert on law ids (must be injective over FRBR work)
_ids = [l["id"] for l in laws]
_dups = {i for i in _ids if _ids.count(i) > 1}
assert not _dups, f"duplicate law ids: {sorted(_dups)[:10]}"
assert len({l["eli"] for l in laws}) == len(laws), "duplicate FRBR works"
# de-dup article ids
seen = set(); arts2 = []
for a in arts:
    if a["id"] in seen: continue
    seen.add(a["id"]); arts2.append(a)
OUT.mkdir(parents=True, exist_ok=True)
lt = pa.Table.from_pylist(laws, schema=pa.schema([(k, pa.int32() if k == "article_count" else pa.string()) for k in laws[0]]))
at = pa.Table.from_pylist(arts2, schema=pa.schema([(k, pa.string()) for k in arts2[0]]))
pq.write_table(lt, OUT / "laws.parquet", compression="zstd")
pq.write_table(at, OUT / "articles.parquet", compression="zstd")
_law_ids = set(_ids)
assert all(a["law_id"] in _law_ids for a in arts2), "orphan articles"
res = {"articles_dropped_dup_id": len(arts) - len(arts2), "laws_rows": lt.num_rows, "articles_rows": at.num_rows, "municipalities": len(munis),
       "laws_with_text": sum(1 for l in laws if len(l["text"]) >= 200),
       "laws_zero_articles": sum(1 for l in laws if l["article_count"] == 0)}
for f in ("laws.parquet", "articles.parquet"):
    p = OUT / f
    res[f] = {"bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
print(json.dumps(res, indent=1))
(OUT.parent / "stage_result.json").write_text(json.dumps(res, indent=1))
