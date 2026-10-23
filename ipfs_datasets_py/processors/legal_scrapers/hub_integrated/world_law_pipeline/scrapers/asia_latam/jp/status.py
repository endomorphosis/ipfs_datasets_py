#!/usr/bin/env python3
"""Summarize JP reiki crawl state -> stdout + staging/asia_latam/_status_jp.json; writes unmatched list."""
import json, collections, sys, csv
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from jp_reiki import classify, STATE, STAGE
seeds = json.load(open(Path(__file__).parent / "seeds_places.json"))
by = collections.defaultdict(collections.Counter)
docs = collections.Counter(); listed = collections.Counter(); places = set(); unmatched_docs = 0
reasons = collections.Counter()
for s in seeds:
    p = STATE / f"{s['seed_id']}.json"
    st = json.loads(p.read_text()) if p.exists() else {"status": "pending"}
    v = st.get("vendor") or classify(s["url"])
    if v == "gyosei" and "g-reiki.net" in s["url"]:
        v = "gyosei(g-reiki.net)"
    by[v]["seeds"] += 1
    by[v][st["status"]] += 1
    docs[v] += st.get("n_docs", 0); listed[v] += st.get("n_listed") or 0
    if st.get("n_docs"):
        if s.get("place_id"): places.add(s["place_id"])
        else: unmatched_docs += st["n_docs"]
    if st.get("reason"): reasons[st["reason"][:70]] += 1
out = {"vendors": {k: dict(v, docs=docs[k], listed=listed[k]) for k, v in by.items()},
       "total_docs": sum(docs.values()), "total_listed": sum(listed.values()), "places_with_docs": len(places),
       "unmatched_seeds": sum(1 for s in seeds if not s.get("place_id")), "unmatched_docs": unmatched_docs,
       "top_reasons": reasons.most_common(15)}
(STAGE / "_status_jp.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
with open(STAGE / "_unmatched_jp.csv", "w", newline="") as fh:
    w = csv.writer(fh); w.writerow(["seed_id", "pref", "name", "url", "jis_code", "qid", "match"])
    for s in seeds:
        if not s.get("place_id"):
            w.writerow([s["seed_id"], s["pref"], s["name"], s["url"], s.get("jis_code"), s.get("qid"), s["match"]])
print(json.dumps(out, ensure_ascii=False, indent=1))
