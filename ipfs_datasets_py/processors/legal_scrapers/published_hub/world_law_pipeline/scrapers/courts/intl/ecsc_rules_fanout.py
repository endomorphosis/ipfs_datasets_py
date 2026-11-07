"""Fan out ECSC rule rows stored under data/lc/lc_rules.jsonl (applies_to MEMBERS) into
per-member data/<cc>/<cc>_rules.jsonl for AG/DM/GD/KN/AI/MS/VG/VC so WORLD_COUNTS reflects
shared ECSC Civil/Criminal Procedure Rules. Dedup by rule_id; never overwrite. LC untouched."""
import json, os, sys, datetime
ROOT = "/workspace/world_courts"
SRC = f"{ROOT}/data/lc/lc_rules.jsonl"
MEMBERS = ["ag", "dm", "gd", "kn", "ai", "ms", "vg", "vc"]  # LC already has them
now = datetime.datetime.now(datetime.UTC).isoformat()
src_rows = [json.loads(l) for l in open(SRC)]
# only rows that declare ECSC applies_to
src_rows = [r for r in src_rows if isinstance(r.get("applies_to"), list) and "LC" in r.get("applies_to", [])]
added = {}
for cc in MEMBERS:
    out = f"{ROOT}/data/{cc}/{cc}_rules.jsonl"
    have = set()
    if os.path.exists(out):
        for l in open(out):
            try: have.add(json.loads(l)["rule_id"])
            except Exception: pass
    new = []
    for r in src_rows:
        rid = r.get("rule_id")
        if not rid or rid in have: continue
        if cc.upper() not in (r.get("applies_to") or []): continue
        row = dict(r)
        # keep shared court_id (lc-*) but note fan-out; do not invent local court_ids
        row["retrieved_at"] = now
        row["fanout_from"] = "lc/lc_rules.jsonl"
        row["needs_review"] = bool(row.get("needs_review", False))
        new.append(row); have.add(rid)
    if "--dry" not in sys.argv and new:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "a") as f:
            for x in new: f.write(json.dumps(x, ensure_ascii=False) + "\n")
    added[cc] = len(new)
print("added", added, "from", len(src_rows), "lc ecsc rows")
