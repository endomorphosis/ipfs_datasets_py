"""Targeted row-terms patch (CoS ruling 2026-10-18 14:27 PT): rewrite only the 'Site terms:' part of `license` and
extras.source_terms for rows from hosts whose override has apply_to_rows=true. No other column or row is touched;
articles.parquet is not touched. usage: patch_za_terms_rows.py ZA_STATE PACK_DIR"""
import os, sys, json, pyarrow as pa, pyarrow.parquet as pq
STATE, PACK = sys.argv[1], sys.argv[2]
ov = json.load(open(os.path.join(STATE, "terms", "terms_overrides.json")))
def key(h):
    for k in (h, h[4:] if h.startswith("www.") else "www." + h):
        if k in ov and ov[k].get("apply_to_rows"): return k
p = os.path.join(PACK, "data", "laws.parquet"); t = pq.read_table(p); rows = t.to_pylist(); n = 0
for r in rows:
    m = json.loads(r["metadata_json"]); e = m.get("extras", {}); h = e.get("host")
    k = key(h) if h and r["source_type"] == "za_municipal_website_document" else None
    if not k: continue
    new = f"{ov[k]['url']}: " + " ".join(ov[k]["quoted"])
    i = r["license"].index("Site terms: ")
    r["license"] = r["license"][:i] + "Site terms: " + new
    if "source_terms" in e: e["source_terms"] = r["license"]
    r["metadata_json"] = json.dumps(m, ensure_ascii=False); n += 1
pq.write_table(pa.Table.from_pylist(rows, schema=t.schema), p, compression="zstd")
print("patched rows:", n)
