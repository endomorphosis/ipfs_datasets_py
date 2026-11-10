"""SG: full Supreme Court bench (CJ, Justices of the Court of Appeal, Judges of the Appellate Division, High Court Judges,
Judicial Commissioners) from the Singapore Government Directory page for the Supreme Court. Names and official titles only;
chambers staff, registrars and all contact details are skipped. Existing rows matched on name slug are not duplicated."""
import json, re, html, datetime, hashlib, os, unicodedata, requests
ROOT = "/workspace/world_courts"; UA = "Mozilla/5.0 (world_courts research; public court data)"
SRC = "https://www.sgdi.gov.sg/organs-of-state/supcourt"; OUT = f"{ROOT}/data/sg/sg_judges.jsonl"
now = datetime.datetime.now(datetime.UTC).isoformat()
r = requests.get(SRC, headers={"User-Agent": UA}, timeout=60); r.raise_for_status(); sha = hashlib.sha256(r.content).hexdigest()
t = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", r.text, flags=re.S)
x = [y for y in (re.sub(r"\s+", " ", html.unescape(z)).strip() for z in re.sub(r"<[^>]+>", "\n", t).split("\n")) if y]
ROLES = {"Chief Justice": ("Chief Justice", "chief"), "Justice of the Court of Appeal": ("Justice of the Court of Appeal", "associate"),
         "Judge of the Appellate Division": ("Judge of the Appellate Division of the High Court", "associate"),
         "Judge": ("Judge of the High Court", "associate"), "Judicial Commissioner": ("Judicial Commissioner of the Supreme Court", "judicial_commissioner")}
HON = re.compile(r"^(DUT|PPA|PB|PBS|PBM|BBM|SC|PJG|PPA\(.\))")
def clean(s):
    s = re.sub(r"^(Chief Justice|Justice|JC)\s+", "", s).strip()
    parts = [p.strip() for p in s.split(",")]
    keep = [parts[0]] + [p for p in parts[1:] if p and not HON.match(p)]
    nm = " ".join(keep); nm = re.sub(r"\s*\(.*?\)", "", nm)
    return " ".join(w.capitalize() if (w.isupper() and len(w) > 1 and "." not in w) else w for w in nm.split())
def slug(s): return re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()).strip("-")
found = []
for i, y in enumerate(x[:-1]):
    if y in ROLES and re.match(r"^(Chief Justice|Justice|JC)\s", x[i + 1]):
        found.append((clean(x[i + 1]), *ROLES[y]))
old = [json.loads(l) for l in open(OUT)] if os.path.exists(OUT) else []; have = {slug(o["name"]) for o in old}; n = 0
with open(OUT, "a") as f:
    for nm, title, pt in found:
        if slug(nm) in have: continue
        f.write(json.dumps({"judge_id": f"sg-supreme-court-{slug(nm)}", "court_id": "sg-supreme-court", "name": nm, "title": title,
            "position_type": pt, "term_start": None, "term_end": None, "status": "sitting", "roster_url": SRC, "source_url": SRC,
            "site_policy": "robots_unknown:sgdi_robots_404|Singapore Government Directory terms of use", "retrieved_at": now, "needs_review": False,
            "extraction": "SGDI Supreme Court organs-of-state page; judicial office holders only (names/official titles), staff and contact details skipped",
            "license": "Singapore Government public directory; no open licence stated", "source_sha256": sha}, ensure_ascii=False) + "\n"); n += 1; have.add(slug(nm))
print("parsed", len(found), "added", n); print([f[0] for f in found])
