"""Curaçao and Caribbean Netherlands (BES) civil procedure codes from the official Dutch government repositories (KOOP):
- CW: Wetboek van Burgerlijke Rechtsvordering (Landsverordening 29 april 2005), CVDR145086 version 1 (geldend vanaf 10-10-2010;
  Curaçao legislation as published in CVDR; later Curaçao amendments not consolidated there -> needs_review)
- BQ: Wetboek van Burgerlijke Rechtsvordering BES (BWBR0028496), toestand 2015-07-01 (current per wetten.overheid.nl SRU, einddatum 9999-12-31)
Article-level rows -> data/<cc>/<cc>_rules.jsonl (dedup by rule_id). Same parser as sx_rv_cvdr_rules.py."""
import json, hashlib, os, urllib.request, datetime, re, time
import xml.etree.ElementTree as ET
W = "/workspace/world_courts"
UA = "WorldCourtsResearchBot/1.0 (court-data research; contact via Benjamin Barber)"
POL = ("robots_unknown:repository.officiele-overheidspublicaties.nl robots.txt empty/not served (robots ignored per user authorization)|"
       "official KOOP repository (Dutch government); {rights}|single XML download")
SRC = [
 dict(cc="cw", rsid="cw-rv", url="https://repository.officiele-overheidspublicaties.nl/cvdr/145086/1/xml/145086_1.xml",
      index="https://lokaleregelgeving.overheid.nl/CVDR145086", raw="rules/raw/cw/CVDR145086_1.xml", court="cw-lower-court",
      rs="Wetboek van Burgerlijke Rechtsvordering (Curaçao; Landsverordening van 29 april 2005)", eff="2010-10-10", review=True,
      rights="CVDR dcterms:rights 'vrij van auteursrecht en databankrecht'",
      note="CVDR145086 version 1 (geldend vanaf 10-10-2010); amendments enacted by Curaçao after 2010 are not consolidated in CVDR"),
 dict(cc="bq", rsid="bq-rv-bes", url="https://repository.officiele-overheidspublicaties.nl/bwb/BWBR0028496/2015-07-01_0/xml/BWBR0028496_2015-07-01_0.xml",
      index="https://wetten.overheid.nl/BWBR0028496/2015-07-01", raw="rules/raw/bq/BWBR0028496_2015-07-01_0.xml", court=None,
      rs="Wetboek van Burgerlijke Rechtsvordering BES (BWBR0028496)", eff="2015-07-01", review=False,
      rights="Dutch statute text (Auteurswet art. 11: no copyright on legislation)",
      note="wetten.overheid.nl toestand 2015-07-01 (current version per SRU, geldig t/m 9999-12-31)"),
]
LEV = {"deel": "Boek", "boek": "Boek", "hoofdstuk": "Boek", "titeldeel": "Titel", "afdeling": "Afdeling", "paragraaf": "Paragraaf"}
BODY = {"lid", "al", "lijst", "tabel", "table"}
def ln(e): return e.tag.split("}")[-1]
def txt(e):
    return re.sub(r"\s+", " ", "".join(x for x in e.itertext())).strip()
def clean(e):
    for p in list(e.iter()):
        for c in list(p):
            if ln(c) in ("meta-data", "brondata", "jcis", "redactie", "noot"): p.remove(c)
    return e
for s in SRC:
    P = f"{W}/{s['raw']}"
    if not os.path.exists(P) or os.path.getsize(P) < 100000:
        open(P, "wb").write(urllib.request.urlopen(urllib.request.Request(s["url"], headers={"User-Agent": UA}), timeout=120).read()); time.sleep(3)
    b = open(P, "rb").read(); sha = hashlib.sha256(b).hexdigest()
    root = clean(ET.fromstring(b)); rows = []
    def walk(e, path):
        for c in e:
            t = ln(c)
            if t in LEV:
                k = c.find("./{*}kop"); h = " ".join(txt(x) for x in k).strip() if k is not None else LEV[t]
                h = re.sub(r"^(BOEK|TITEL|AFDELING|PARAGRAAF|HOOFDSTUK) ", lambda m: m.group(1).capitalize() + " ", h)
                walk(c, path + [h])
            elif t == "artikel":
                nr = c.find("./{*}kop/{*}nr"); kt = c.find("./{*}kop/{*}titel")
                num = (nr.text or "").strip() if nr is not None else ""
                parts = []
                for ch in c:
                    if ln(ch) not in BODY: continue
                    if ln(ch) == "lid":
                        n = ch.find("./{*}lidnr"); body = " ".join(txt(x) for x in ch if ln(x) != "lidnr")
                        parts.append((((n.text or "").strip() if n is not None else "") + " " + body).strip())
                    else: parts.append(txt(ch))
                rows.append(dict(num=num, title=txt(kt) if kt is not None else None, part=" > ".join(path) or None, text="\n".join(p for p in parts if p)))
            else: walk(c, path)
    walk(root, [])
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(); seen, out = set(), []
    for r in rows:
        if not r["num"]: continue
        rid = f"{s['rsid']}:art{r['num']}"; n = 2
        while rid in seen: rid = f"{s['rsid']}:art{r['num']}-{n}"; n += 1
        seen.add(rid)
        out.append(dict(rule_id=rid, rule_set_id=s["rsid"], court_id=s["court"], jurisdiction=s["cc"].upper(), applies_to=[s["cc"].upper()],
            rule_set=s["rs"], rule_number=f"Artikel {r['num']}", title=r["title"], part=r["part"], text=r["text"], effective_date=s["eff"],
            pdf_path=None, pdf_sha256=None, source_sha256=sha, source_url=s["url"], index_url=s["index"], source_kind="official",
            site_policy=POL.format(rights=s["rights"]), license="public legislation; " + s["rights"], retrieved_at=now, language="nl",
            needs_review=s["review"] or ("-" in rid.split(":")[1]) or len(r["text"]) < 10, version_note=s["note"]))
    OUT = f"{W}/data/{s['cc']}/{s['cc']}_rules.jsonl"
    existing = {json.loads(l)["rule_id"] for l in open(OUT)} if os.path.exists(OUT) else set()
    new = [r for r in out if r["rule_id"] not in existing]
    if os.environ.get("DRY"):
        for r in out[:1] + out[-1:]: print(s["cc"], r["rule_number"], "|", r["part"], "|", r["text"][:150])
        print(s["cc"], "parsed", len(out), "dups", [r["rule_id"] for r in out if "-" in r["rule_id"].split(":")[1]][:8], "short", sum(len(r["text"]) < 10 for r in out)); continue
    with open(OUT, "a") as f:
        for r in new: f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(s["cc"], "parsed", len(out), "new", len(new), "review", sum(r["needs_review"] for r in new))
