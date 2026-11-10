"""State trial-court judges from official static directories only (names + titles; no contact details kept).
Sources: DE Superior Court, NE district/county/separate-juvenile directories, WI circuit judges, IA district judges & magistrates (8 districts), ND district court judges."""
import re, json, sys, datetime, collections
sys.path.insert(0, "/workspace/world_courts/scrapers/courts"); 
import us_cos_ingest as I, us_directory_extract as de
from us_tjx import names as hon_names
D = I.D
IA = [f"https://www.iowacourts.gov/iowa-courts/district-court/judicial-district-{n}/{s}/" for n, s in ((1, "judges-and-magistrates-district-1"), (2, "judges-and-magistrates"), (3, "judges-and-magistrates"), (4, "judges-and-magistrates"), (5, "judges-and-magistrates"), (6, "judges-and-magistrates"), (7, "judges-and-magistrates"), (8, "district-8-judges-and-magistrates"))]
SRC = [("DE", "https://courts.delaware.gov/superior/aboutus/judges.aspx", "hon", "Delaware Superior Court", "US-DE-superior"),
       ("NE", "https://supremecourt.nebraska.gov/directories/district-court-judges", "hon", "Nebraska District Court", "US-NE-district"),
       ("NE", "https://supremecourt.nebraska.gov/directories/county-court-judges", "hon", "Nebraska County Court", "US-NE-county"),
       ("NE", "https://supremecourt.nebraska.gov/directories/separate-juvenile-court-judges", "hon", "Nebraska Separate Juvenile Court", "US-NE-juvenile"),
       ("WI", "https://www.wicourts.gov/courts/circuit/judges.htm", "wi", "Wisconsin Circuit Court", "US-WI-circuit"),
       ("ND", "https://www.ndcourts.gov/district-court/district-court-judges", "nd", "North Dakota District Court", "US-ND-district")] + \
      [("IA", u, "ia", f"Iowa District Court, Judicial District {i+1}", f"US-IA-district-{i+1}") for i, u in enumerate(IA)]
IAT = re.compile(r"^(Chief Judge|District Court Judge|District Associate Judge|Associate Juvenile Judge|Associate Probate Judge|Senior Judge|Magistrate|Judicial Magistrate)\b")
NMOK = re.compile(r"^[A-Z][a-zA-Z'\-]+\.?(?: [A-Z][a-zA-Z'\-\"]*\.?){1,4}(?:,? (?:Jr\.|Sr\.|II|III|IV))?$")
def parse(kind, h):
    L = [re.sub(r"\s+", " ", l).strip() for l in de.totext(h).split("\n")]; L = [l for l in L if l]; out = []
    if kind == "hon":
        for t, n in hon_names(h): out.append((n, "Judge" if t in ("Hon.", "Honorable") else t))
    elif kind == "wi":
        for l in L:
            m = re.match(r"^([A-Z][\w'\-]+(?: [A-Z][\w'\-]+)?(?:, (?:Jr\.|Sr\.|II|III))?), Hon\. (.+)$", l)
            if m: out.append((f"{m.group(2)} {m.group(1)}", "Circuit Court Judge"))
    elif kind == "ia":
        for i in range(len(L) - 1):
            m = IAT.match(L[i + 1])
            if m and NMOK.match(L[i]) and not re.search(r"(?i)court|district|judge", L[i]): out.append((L[i], L[i + 1].split(":")[0]))
    elif kind == "nd":
        for i in range(len(L) - 2):
            if NMOK.match(L[i]) and re.match(r"^(Presiding )?(District Court )?Judge$|^District Judge$", L[i + 1]) and not re.search(r"(?i)court|judge", L[i]):
                nxt = " ".join(L[i + 2:i + 4])
                if re.search(r"\d{4} - ?\d{4}", nxt): continue
                out.append((L[i], L[i + 1]))
    return list(dict.fromkeys(out))
if __name__ == "__main__":
    now = datetime.datetime.now(datetime.UTC).isoformat(); rows = []; rep = {}
    for st, u, kind, court, cid in SRC:
        h, pol, err = I.fetch(u)
        if not h: rep[u] = err; continue
        got = parse(kind, h); rep[u] = len(got)
        for n, t in got:
            s = re.sub(r"[^a-z0-9]+", "-", n.lower()).strip("-")
            rows.append({"judge_id": f"US-{st}:trial:{cid}:{s}", "name": n, "title": t, "court_level": "trial", "court_name": court, "court_id": cid, "subdivision": f"US-{st}",
                "roster_url": u, "source_url": u, "site_policy": pol, "retrieved_at": now, "extraction": f"trial_roster:{kind}", "needs_review": True})
    u = {r["judge_id"]: r for r in rows}
    old = [l for l in open(D + "us_judges.jsonl") if ':trial:' not in l.split('"judge_id": "', 1)[1][:60]]
    with open(D + "us_judges.jsonl", "w") as f: f.writelines(old + [json.dumps(r) + "\n" for r in u.values()])
    print(json.dumps(rep, indent=0)); print(collections.Counter(r["subdivision"] for r in u.values()), len(u))
