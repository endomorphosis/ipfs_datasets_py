"""Sint Maarten, Curaçao and Caribbean Netherlands (BES) criminal procedure codes (Wetboek van Strafvordering) from the official Dutch government repositories (KOOP):
- SX: CVDR142469_3; CW: CVDR144089_1 (geldend vanaf 10-10-2010;
  Curaçao legislation as published in CVDR; later Curaçao amendments not consolidated there -> needs_review)
- BQ: Wetboek van Burgerlijke Rechtsvordering BES (BWBR0028496), toestand 2015-07-01 (current per wetten.overheid.nl SRU, einddatum 9999-12-31)
Article-level rows -> data/<cc>/<cc>_rules.jsonl (dedup by rule_id). Same parser as cw_bq_rv_overheid_rules.py."""
import json, hashlib, os, urllib.request, datetime, re, time
import xml.etree.ElementTree as ET
W = "/workspace/world_courts"
UA = "WorldCourtsResearchBot/1.0 (court-data research; contact via Benjamin Barber)"
POL = ("robots_unknown:repository.officiele-overheidspublicaties.nl robots.txt empty/not served (robots ignored per user authorization)|"
       "official KOOP repository (Dutch government); {rights}|single XML download")
SRC = [
 dict(cc="sx", rsid="sx-sv", url="https://repository.officiele-overheidspublicaties.nl/cvdr/CVDR142469/3/xml/CVDR142469_3.xml",
      index="https://lokaleregelgeving.overheid.nl/CVDR142469", raw="rules/raw/sx/CVDR142469_3.xml", court="sx-lower-court",
      rs="Wetboek van Strafvordering (Sint Maarten; Landsverordening van 5 november 1996)", eff="2015-05-30", review=False,
      rights="CVDR dcterms:rights 'vrij van auteursrecht en databankrecht'",
      note="CVDR142469 version 3 (in force 2015-05-30 per CVDR); amendments after 2015 may not be consolidated"),
 dict(cc="cw", rsid="cw-sv", url="https://repository.officiele-overheidspublicaties.nl/cvdr/144089/1/xml/144089_1.xml",
      index="https://lokaleregelgeving.overheid.nl/CVDR144089", raw="rules/raw/cw/CVDR144089_1.xml", court="cw-lower-court",
      rs="Wetboek van Strafvordering (Curaçao; Landsverordening van 5 november 1996)", eff="2010-10-10", review=True,
      rights="CVDR dcterms:rights 'vrij van auteursrecht en databankrecht'",
      note="CVDR144089 version 1 (geldend vanaf 10-10-2010, bestendiging Antilliaanse regelgeving); later Curaçao amendments not consolidated in CVDR"),
 dict(cc="bq", rsid="bq-sv-bes", url="https://repository.officiele-overheidspublicaties.nl/bwb/BWBR0028681/2025-07-01_0/xml/BWBR0028681_2025-07-01_0.xml",
      index="https://wetten.overheid.nl/BWBR0028681/2025-07-01", raw="rules/raw/bq/BWBR0028681_2025-07-01_0.xml", court=None,
      rs="Wetboek van Strafvordering BES (BWBR0028681)", eff="2025-07-01", review=False,
      rights="Dutch statute text (Auteurswet art. 11: no copyright on legislation)",
      note="wetten.overheid.nl toestand 2025-07-01 (current version per SRU, geldig t/m 9999-12-31)"),
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
                rows.append(dict(num=num, title=txt(kt) if kt is not None else None, part=" > ".join(p for p in path if p) or None, text="\n".join(p for p in parts if p)))
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
