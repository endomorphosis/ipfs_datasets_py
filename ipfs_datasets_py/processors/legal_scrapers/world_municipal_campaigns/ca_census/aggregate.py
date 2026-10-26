#!/usr/bin/env python3
"""Canada census step 3: aggregate census_raw.jsonl -> stats JSON + the
publishable census JSONL (sorted by SGC) in the census artifacts dir."""
import json, collections
from pathlib import Path

HERE = Path(__file__).resolve().parent
CENSUS = HERE.parent
rows = [json.loads(l) for l in open(CENSUS / "census_raw.jsonl")]
rows.sort(key=lambda r: r["sgc"])
assert len({r["sgc"] for r in rows}) == len(rows)

out_jsonl = CENSUS / "ca_platform_census_2026-10-12.jsonl"
with open(out_jsonl, "w") as fh:
    for r in rows:
        fh.write(json.dumps(r, ensure_ascii=False) + "\n")

def cnt(key, data=rows):
    return dict(collections.Counter(r.get(key) for r in data).most_common())

STRONG = {"index_with_pdfs", "direct_pdf_links_on_homepage"}
def reachable(r):
    return (r.get("website_url") and r.get("census_status") == "classified"
            and r.get("robots_posture") == "allowed"
            and r.get("platform") not in ("CivicWeb", "eScribe"))
def strong(r):
    return reachable(r) and r.get("bylaws_presence") in STRONG

stats = {
    "total_csds": len(rows),
    "url_source": cnt("url_source"),
    "resolved": sum(1 for r in rows if r.get("website_url")),
    "census_status": cnt("census_status"),
    "platform_national": cnt("platform"),
    "robots_posture": cnt("robots_posture"),
    "bylaws_presence": cnt("bylaws_presence"),
    "reachable_towns": sum(1 for r in rows if reachable(r)),
    "strong_towns": sum(1 for r in rows if strong(r)),
    "by_province": {},
    "qc_platform": cnt("platform", [r for r in rows if r["province"] == "Quebec"]),
}
for prov, data in sorted(((p, [r for r in rows if r["province"] == p])
                          for p in {r["province"] for r in rows}), key=lambda x: -len(x[1])):
    stats["by_province"][prov] = {
        "total": len(data),
        "resolved": sum(1 for r in data if r.get("website_url")),
        "platform": cnt("platform", data),
        "robots_posture": cnt("robots_posture", data),
        "reachable": sum(1 for r in data if reachable(r)),
        "strong": sum(1 for r in data if strong(r)),
    }
# ranked families by reachable strong towns
fam = collections.defaultdict(lambda: {"strong": 0, "reachable": 0, "total": 0})
for r in rows:
    f = r.get("platform") or "unclassified"
    fam[f]["total"] += 1
    if reachable(r): fam[f]["reachable"] += 1
    if strong(r): fam[f]["strong"] += 1
stats["families_ranked"] = sorted(
    ({"family": k, **v} for k, v in fam.items()),
    key=lambda d: (-d["strong"], -d["reachable"]))
json.dump(stats, open(CENSUS / "census_stats.json", "w"), indent=1, ensure_ascii=False)
print(json.dumps({k: stats[k] for k in ("total_csds", "resolved", "reachable_towns",
                                         "strong_towns", "url_source", "census_status")}, indent=1))
print("families:", json.dumps(stats["families_ranked"], indent=1))
