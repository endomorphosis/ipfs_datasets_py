"""Article III judges currently in service (no termination) from the FJC Biographical Directory public CSV export (fjc.gov/sites/default/files/history/judges.csv).
Kept fields: public name, appointment title, court, commission date, status (active/senior/chief). No biographical/demographic fields. Linked to us-fed-* court_ids."""
import csv, json, re, datetime
D = "/workspace/world_courts/data/us/"; SRC = "https://www.fjc.gov/history/judges/biographical-directory-article-iii-federal-judges-export"
CSVU = "https://www.fjc.gov/sites/default/files/history/judges.csv"
B = [json.loads(l) for l in open(D + "us_federal_courts.jsonl")]
ORD = {"First":"1","Second":"2","Third":"3","Fourth":"4","Fifth":"5","Sixth":"6","Seventh":"7","Eighth":"8","Ninth":"9","Tenth":"10","Eleventh":"11"}
def court_id(n):
    if n == "Supreme Court of the United States": return "us-fed-scotus"
    if n == "U.S. Court of International Trade": return "us-fed-cit"
    m = re.match(r"U\.S\. Court of Appeals for the (\w+) Circuit", n)
    if m:
        if m.group(1) == "Federal": return "us-fed-cafc"
        if m.group(1) in ORD: return "us-fed-ca" + ORD[m.group(1)]
    if n == "U.S. Court of Appeals for the District of Columbia Circuit": return "us-fed-cadc"
    if n == "U.S. District Court for the District of Columbia": return "us-fed-dcd"
    m = re.match(r"U\.S\. District Court for the (?:(Northern|Southern|Eastern|Western|Middle|Central) )?District of (.+)$", n)
    if m:
        d, st = m.group(1), m.group(2).replace("the ", "")
        for b in B:
            if b["court_type"] != "district": continue
            lab = b["name"].split(", ", 1)[1]
            if lab.startswith(st) and ((d and d in lab) or (not d and lab.strip() == st)): return b["court_id"]
    return None
rows = []; miss = set(); now = datetime.datetime.now(datetime.UTC).isoformat()
for r in csv.DictReader(open("/workspace/world_courts/data/ref/us_fed/fjc_judges.csv", encoding="utf-8")):
    for i in range(1, 7):
        n = r.get(f"Court Name ({i})")
        if not n or r.get(f"Termination ({i})"): continue
        cid = court_id(n)
        if not cid: miss.add(n)
        name = " ".join(x for x in (r["First Name"], r["Middle Name"], r["Last Name"], r["Suffix"]) if x).strip()
        senior = bool(r.get(f"Senior Status Date ({i})")); chief = bool(r.get(f"Service as Chief Judge, Begin ({i})")) and not r.get(f"Service as Chief Judge, End ({i})") and not senior
        rows.append({"judge_id": f"US-fed:{cid}:{r['jid']}", "name": name, "title": r.get(f"Appointment Title ({i})"), "status": "senior" if senior else "active",
            "is_chief": chief, "court_name": n, "court_id": cid, "court_level": "federal", "subdivision": "US", "commission_date": r.get(f"Commission Date ({i})") or None,
            "senior_status_date": r.get(f"Senior Status Date ({i})") or None, "fjc_jid": r["jid"], "roster_url": SRC, "source_url": CSVU, "site_policy": "robots_allowed:crawl_delay_30",
            "license": "US federal government work (public domain)", "retrieved_at": now, "extraction": "fjc_csv_export", "needs_review": False})
print("rows", len(rows), "unmapped courts", miss)
with open(D + "us_federal_judges.jsonl", "w") as f:
    for x in rows: f.write(json.dumps(x) + "\n")
old = [l for l in open(D + "us_judges.jsonl") if not l.startswith('{"judge_id": "US-fed:')]
with open(D + "us_judges.jsonl", "w") as f: f.writelines(old + [json.dumps(x) + "\n" for x in rows])
import collections; print(collections.Counter((x["court_id"] or "?")[:9] for x in rows), collections.Counter(x["status"] for x in rows))
