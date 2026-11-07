"""Run us_forms on the Chief-of-Staff seed form index URLs (inbox/from_cos.jsonl, kind=forms); robots respected by us_forms.policy."""
import json, sys
sys.path.insert(0, "/workspace/world_courts/scrapers/courts")
import us_forms as F
S = {}
for l in open("/workspace/world_courts/inbox/from_cos.jsonl"):
    s = json.loads(l)
    if s["kind"] == "forms": S.setdefault(s["state"], []).append(s["url"])
for st, u in S.items(): F.SEEDS[st] = u + [x for x in F.SEEDS.get(st, []) if x not in u]
F.run(sorted(S))
