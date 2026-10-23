#!/usr/bin/env python3
"""Final merge: registry (3,489 municipal CSDs) LEFT JOIN resolved URLs
LEFT JOIN census classifications -> complete census_raw_all.jsonl with one
row per CSD, so aggregate.py can run over the full universe.

- resolved dedupe: prefer rows with a website_url; among those prefer
  source rank pilot_seed > pattern/civicweb/escribe > qc_mamh > on_fippa.
- malformed directory URLs (HTML anchor cells) are discarded with a note.
- towns sharing one resolved host are flagged (same-name ambiguity).
- towns never reached by the resolver get resolution_not_attempted;
  resolved-but-unclassified towns get resolved_not_classified.
"""
import json
import re
import collections
from pathlib import Path

HERE = Path(__file__).resolve().parent
CENSUS = HERE.parent
PILOT = CENSUS.parent / "ca_pilot"

reg = [json.loads(l) for l in open(PILOT / "sgc_registry_2021.jsonl")]
muni = {r["sgc"]: r for r in reg if r["municipal_government"]}
print(f"municipal CSDs: {len(muni)}")

SRC_RANK = {"pilot_seed": 0, "pattern_http": 1, "civicweb_pattern": 1,
            "escribe_pattern": 1, "qc_mamh_repertoire": 2,
            "on_fippa_directory": 3}

resolved = {}
malformed = {}
for l in open(CENSUS / "sources" / "resolved.jsonl"):
    r = json.loads(l)
    url = r.get("website_url")
    if url and ("<" in url or " " in url):
        m = re.search(r'href="(https?://[^"]+)"', url)
        malformed[r["sgc"]] = url
        url = None  # discard malformed directory URL
        r = {**r, "website_url": None}
    cur = resolved.get(r["sgc"])
    if cur is None:
        resolved[r["sgc"]] = r
        continue
    cur_has = bool(cur.get("website_url"))
    new_has = bool(url)
    if new_has and not cur_has:
        resolved[r["sgc"]] = r
    elif new_has and cur_has:
        if SRC_RANK.get(r.get("url_source"), 9) < SRC_RANK.get(cur.get("url_source"), 9):
            resolved[r["sgc"]] = r

pass1 = {}
p1f = CENSUS / "sources" / "resolved_pass1.jsonl"
if p1f.exists():
    for l in open(p1f):
        r = json.loads(l)
        pass1[r["sgc"]] = r

census = {}
STATUS_RANK = {"classified": 0, "walled": 1, "site_unreachable": 2,
               "site_error": 3, "no_site_found": 4}
for l in open(CENSUS / "census_raw.jsonl"):
    r = json.loads(l)
    cur = census.get(r["sgc"])
    if cur is None or STATUS_RANK.get(r.get("census_status"), 9) < STATUS_RANK.get(cur.get("census_status"), 9):
        census[r["sgc"]] = r

host_claims = collections.defaultdict(set)
for sgc, r in resolved.items():
    if r.get("website_url"):
        host = re.sub(r"^www\.", "", re.sub(r"^https?://", "", r["website_url"]).split("/")[0].lower())
        host_claims[host].add(sgc)
shared = {h for h, s in host_claims.items() if len(s) > 1}

out = []
for sgc, g in sorted(muni.items()):
    base = {"sgc": sgc, "name": g["name"], "province": g["province"],
            "csd_type": g["csd_type"]}
    notes = []
    if sgc in malformed:
        notes.append("directory_url_malformed_discarded")
    if sgc in census:
        row = {**base, **census[sgc]}
        # census row fields win, but keep registry identity fields
        row.update(base)
        if not row.get("website_url") and sgc in resolved and resolved[sgc].get("website_url"):
            # classifier stamped no_site_found from an earlier snapshot;
            # a later resolution pass found the site
            row = {**base, "website_url": resolved[sgc]["website_url"],
                   "url_source": resolved[sgc].get("url_source"),
                   "census_status": "resolved_not_classified",
                   "platform": None, "bylaws_presence": "unknown",
                   "robots_posture": "unknown", "bylaw_index_url": None}
            notes.append("resolved_after_census_snapshot")
    elif sgc in resolved and resolved[sgc].get("website_url"):
        row = {**base, "website_url": resolved[sgc]["website_url"],
               "url_source": resolved[sgc].get("url_source"),
               "census_status": "resolved_not_classified",
               "platform": None, "bylaws_presence": "unknown",
               "robots_posture": "unknown", "bylaw_index_url": None}
    elif sgc in resolved:
        row = {**base, "website_url": None,
               "url_source": resolved[sgc].get("url_source"),
               "census_status": "no_site_found", "platform": None,
               "bylaws_presence": "unknown", "robots_posture": "unknown",
               "bylaw_index_url": None}
    elif sgc in pass1 and not pass1[sgc].get("website_url"):
        # attempted in pass 1 (two-candidate), pass 2 did not reach it
        row = {**base, "website_url": None, "url_source": None,
               "census_status": "no_site_found", "platform": None,
               "bylaws_presence": "unknown", "robots_posture": "unknown",
               "bylaw_index_url": None}
        notes.append("pass1_attempted_pass2_not_reached")
    else:
        row = {**base, "website_url": None, "url_source": None,
               "census_status": "resolution_not_attempted", "platform": None,
               "bylaws_presence": "unknown", "robots_posture": "unknown",
               "bylaw_index_url": None}
    if row.get("website_url"):
        host = re.sub(r"^www\.", "", re.sub(r"^https?://", "", row["website_url"]).split("/")[0].lower())
        if host in shared:
            notes.append("shared_host_multiple_sgcs")
    if notes:
        row["notes"] = ";".join(notes)
    out.append(row)

with open(CENSUS / "census_raw_all.jsonl", "w") as fh:
    for r in out:
        fh.write(json.dumps(r, ensure_ascii=False) + "\n")
print(f"wrote {len(out)} rows")
print("status:", collections.Counter(r["census_status"] for r in out))
print("resolved:", sum(1 for r in out if r.get("website_url")))
