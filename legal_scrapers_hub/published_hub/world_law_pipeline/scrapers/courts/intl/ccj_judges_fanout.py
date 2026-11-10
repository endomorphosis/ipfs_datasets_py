"""Copy CCJ sitting judges from data/tt/tt_judges.jsonl (applies_to BB/BZ/DM/GY/TT)
into BB/BZ/DM/GY judges files. Dedup by judge_id."""
import json, os, sys, datetime
ROOT = "/workspace/world_courts"
SRC = f"{ROOT}/data/tt/tt_judges.jsonl"
MEMBERS = ["bb", "bz", "dm", "gy"]
now = datetime.datetime.now(datetime.UTC).isoformat()
src = [json.loads(l) for l in open(SRC) if "ccj-" in l or '"jurisdiction": "CCJ"' in l]
src = [r for r in (json.loads(l) for l in open(SRC)) if r.get("jurisdiction") == "CCJ" or str(r.get("judge_id","")).startswith("ccj-")]
added = {}
for cc in MEMBERS:
    out = f"{ROOT}/data/{cc}/{cc}_judges.jsonl"
    have = set()
    if os.path.exists(out):
        for l in open(out):
            try: have.add(json.loads(l)["judge_id"])
            except Exception: pass
    new = []
    for r in src:
        if cc.upper() not in (r.get("applies_to") or []): continue
        if r["judge_id"] in have: continue
        row = dict(r); row["retrieved_at"] = now; row["fanout_from"] = "tt/tt_judges.jsonl"
        new.append(row); have.add(r["judge_id"])
    if "--dry" not in sys.argv and new:
        with open(out, "a") as f:
            for x in new: f.write(json.dumps(x, ensure_ascii=False) + "\n")
    added[cc] = len(new)
print("added", added, "from", len(src))
