"""Sint Maarten: Wetboek van Burgerlijke Rechtsvordering (Landsverordening houdende vaststelling van een nieuw
Wetboek van Burgerlijke Rechtsvordering), version CVDR143465_2 in force since 2014-04-01 (AB 2014 no. 12),
from the official Dutch government decentral-legislation repository (CVDR, repository.officiele-overheidspublicaties.nl),
where Sint Maarten publishes its legislation. CVDR rights: free of copyright and database right.
Article-level rows -> data/sx/sx_rules.jsonl (dedup by rule_id)."""
import json, hashlib, os, urllib.request, datetime, re
import xml.etree.ElementTree as ET
W = "/workspace/world_courts"; RAW = f"{W}/rules/raw/sx"; OUT = f"{W}/data/sx/sx_rules.jsonl"
UA = "WorldCourtsResearchBot/1.0 (court-data research; contact via Benjamin Barber)"
URL = "https://repository.officiele-overheidspublicaties.nl/CVDR/CVDR143465/2/xml/CVDR143465_2.xml"
INDEX = "https://lokaleregelgeving.overheid.nl/CVDR143465"
P = f"{RAW}/CVDR143465_2.xml"
POLICY = ("robots_unknown:repository.officiele-overheidspublicaties.nl robots.txt empty/not served (robots ignored per user authorization)|"
          "official CVDR repository (KOOP, Dutch government); dcterms:rights 'vrij van auteursrecht en databankrecht'|single XML download")
RSID = "sx-rv"; RS = "Wetboek van Burgerlijke Rechtsvordering (Sint Maarten; P.B. 2005 no. 67 inwtr., as amended by AB 2014 no. 12)"
os.makedirs(RAW, exist_ok=True)
if not os.path.exists(P) or os.path.getsize(P) < 100000:
    open(P, "wb").write(urllib.request.urlopen(urllib.request.Request(URL, headers={"User-Agent": UA}), timeout=120).read())
b = open(P, "rb").read(); sha = hashlib.sha256(b).hexdigest()
root = ET.fromstring(b)
def ln(e): return e.tag.split("}")[-1]
def txt(e): return re.sub(r"\s+", " ", "".join(e.itertext())).strip()
LEV = {"deel": "Boek", "titeldeel": "Titel", "afdeling": "Afdeling", "paragraaf": "Paragraaf"}
rows = []
def walk(e, path):
    for c in e:
        t = ln(c)
        if t in LEV:
            k = c.find("./{*}kop"); h = " ".join(txt(x) for x in k).strip() if k is not None else LEV[t]; h = (h[:1] + h[1:].lower()) if h.isupper() else re.sub(r"^(BOEK|TITEL|AFDELING|PARAGRAAF) ", lambda m: m.group(1).capitalize() + " ", h)
            walk(c, path + [h])
        elif t == "artikel":
            k = c.find("./{*}kop"); nr = c.find("./{*}kop/{*}nr")
            num = (nr.text or "").strip() if nr is not None else txt(k)
            ktitle = c.find("./{*}kop/{*}titel")
            parts = []
            for ch in c:
                if ln(ch) == "kop": continue
                if ln(ch) == "lid":
                    n = ch.find("./{*}lidnr"); body = " ".join(txt(x) for x in ch if ln(x) != "lidnr")
                    parts.append(((n.text or "").strip() + " " + body).strip())
                else: parts.append(txt(ch))
            rows.append(dict(num=num, title=txt(ktitle) if ktitle is not None else None, part=" > ".join(path) or None, text="\n".join(p for p in parts if p)))
        else:
            walk(c, path)
reg = root.find(".//{*}regeling"); walk(reg, [])
now = datetime.datetime.now(datetime.timezone.utc).isoformat()
seen, out = set(), []
for r in rows:
    if not r["num"]: continue
    rid = f"{RSID}:art{r['num']}"; n = 2
    while rid in seen: rid = f"{RSID}:art{r['num']}-{n}"; n += 1
    seen.add(rid)
    out.append(dict(rule_id=rid, rule_set_id=RSID, court_id="sx-lower-court", jurisdiction="SX", applies_to=["SX"],
        rule_set=RS, rule_number=f"Artikel {r['num']}", title=r["title"], part=r["part"], text=r["text"],
        effective_date="2014-04-01", pdf_path=None, pdf_sha256=None, source_sha256=sha, source_url=URL, index_url=INDEX,
        source_kind="official", site_policy=POLICY, license="Sint Maarten legislation; CVDR: free of copyright and database right",
        retrieved_at=now, language="nl", needs_review=("-" in rid.split(":")[1]) or len(r["text"]) < 10,
        version_note="CVDR143465 version 2 (geldend 01-04-2014 t/m heden per CVDR); CVDR notes text not yet adapted to the 10-10-10 constitutional change; later amendments after AB 2014 no. 12 may not be consolidated"))
existing = {json.loads(l)["rule_id"] for l in open(OUT)} if os.path.exists(OUT) else set()
new = [r for r in out if r["rule_id"] not in existing]
if os.environ.get("DRY"): 
    for r in out[:2] + out[-2:]: print(r["rule_number"], "|", r["part"], "|", r["text"][:120])
    print("dups", [r["rule_id"] for r in out if "-" in r["rule_id"].split(":")[1]][:10]); print("parsed", len(out)); raise SystemExit
with open(OUT, "a") as f:
    for r in new: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("parsed", len(out), "new", len(new), "review", sum(r["needs_review"] for r in new))
