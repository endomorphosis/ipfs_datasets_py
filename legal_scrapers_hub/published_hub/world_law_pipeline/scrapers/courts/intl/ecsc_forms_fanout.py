"""Fan out ECSC form metadata rows from data/lc/lc_forms.jsonl into member
data/<cc>/<cc>_forms.jsonl (AG/DM/GD/KN/AI/MS/VG/VC). PDF binaries stay under forms/lc/
(shared pdf_path). Dedup by form_id / pdf_sha256."""
import json, os, sys, datetime
ROOT = "/workspace/world_courts"
SRC = f"{ROOT}/data/lc/lc_forms.jsonl"
MEMBERS = ["ag", "dm", "gd", "kn", "ai", "ms", "vg", "vc"]
now = datetime.datetime.now(datetime.UTC).isoformat()
src = [json.loads(l) for l in open(SRC)]
added = {}
for cc in MEMBERS:
    out = f"{ROOT}/data/{cc}/{cc}_forms.jsonl"
    have = set()
    if os.path.exists(out):
        for l in open(out):
            try:
                r = json.loads(l)
                have.add(r.get("form_id")); have.add(r.get("pdf_sha256"))
            except Exception: pass
    new = []
    for r in src:
        if cc.upper() not in (r.get("applies_to") or []): continue
        if r.get("form_id") in have or r.get("pdf_sha256") in have: continue
        row = dict(r)
        row["retrieved_at"] = now
        row["fanout_from"] = "lc/lc_forms.jsonl"
        new.append(row)
        have.add(row.get("form_id")); have.add(row.get("pdf_sha256"))
    if "--dry" not in sys.argv and new:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "a") as f:
            for x in new: f.write(json.dumps(x, ensure_ascii=False) + "\n")
    added[cc] = len(new)
print("added", added)
