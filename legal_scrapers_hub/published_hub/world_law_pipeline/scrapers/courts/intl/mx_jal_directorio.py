"""MX-JAL: first-instance juzgados (+ judges' public names/titles) from the Consejo de la Judicatura de Jalisco
official 'Directorio Oficial' PDF (transparency art. 8 fr. I inciso j). Judges' emails/phones are NOT stored for judges;
the juzgado's official phone is kept on the court row. Dedup vs existing names."""
import json, sys, re, datetime, hashlib
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_common import *
RAW = f"{ROOT}/rules/raw/mx_jal/directorio.pdf"; TXT = f"{ROOT}/rules/raw/mx_jal/d.txt"
SRC = "https://cjj.gob.mx/files/transparencia/fraccion1/ART08_FRACI_INCISOJ.PDF"
CO = f"{ROOT}/data/mx/mx_courthouses.jsonl"; JO = f"{ROOT}/data/mx/mx_judges.jsonl"
sha = hashlib.sha256(open(RAW, "rb").read()).hexdigest(); now = datetime.datetime.now(datetime.UTC).isoformat()
L = [l.rstrip() for l in open(TXT, encoding="utf-8")]
rows = [json.loads(l) for l in open(CO)]; seen = {norm(r["name"]) for r in rows}; ids = {r["court_id"] for r in rows}
jids = {json.loads(l)["judge_id"] for l in open(JO)}
parent = next((r["court_id"] for r in rows if r.get("subdivision") == "MX-JAL" and r.get("record_type") == "court_body" and "Supremo" in r["name"]), "mx-tsj-jal")
def slug(s): return re.sub(r"[^a-z0-9]+", "-", norm(s)).strip("-")[:80]
courts, judges = [], []
for i, l in enumerate(L):
    m = re.match(r"^\s*(Juez[a]?\s+.+?)\s*$", l)
    if not m or i + 1 >= len(L): continue
    nxt = L[i + 1].strip(); pm = re.match(r"^(.*Partido Judicial)", nxt)
    if not pm: continue
    title = re.sub(r"\s{2,}.*", "", m.group(1)); partido = re.sub(r"^Primera Instancia,\s*", "", pm.group(1)).strip()
    jname = tel = dom = None
    for k in range(i + 2, min(i + 12, len(L))):
        s = L[k].strip()
        if not jname and re.match(r"^(Lic|Mtr|Dr|Mtra|Mtro|L\.|Abog)", s): jname = re.sub(r"\s{2,}.*", "", s); tel = (re.search(r"Tel\.?\s*(.+)$", s) or [None, None])[1]
        if s.startswith("Domicilio"):
            dom = re.sub(r"^Domicilio\s*", "", s)
            if k + 1 < len(L) and L[k + 1].startswith(" " * 10) and L[k + 1].strip(): dom += " " + L[k + 1].strip()
            break
        if re.match(r"^\s*Juez", L[k]): break
    court = re.sub(r"^Juez[a]?\s+", "Juzgado ", title)
    city = (re.search(r",\s*([^,]+),\s*Jalisco", dom or "") or [None, None])[1]
    cp = (re.search(r"C\.\s*P\.\s*(\d{5})", dom or "") or [None, None])[1]
    cid = f"mx-jal-{slug(court)}"
    if norm(court) in seen or cid in ids: continue
    seen.add(norm(court)); ids.add(cid); nl = court.lower()
    lvl = "family" if "familiar" in nl else "juvenile" if "adolesc" in nl else "trial_limited" if "menor" in nl or "paz" in nl else "trial_general"
    courts.append({"court_id": cid, "record_type": "courthouse", "name": court, "name_local": court, "level": lvl, "court_system": "state",
      "country_code": "MX", "subdivision": "MX-JAL", "jurisdiction": partido, "parent_court_id": parent,
      "address": {"street": dom, "city": city, "postcode": cp, "region": "Jalisco", "country": "México"}, "geo": {"lat": None, "lon": None},
      "phone": tel, "website": "https://cjj.gob.mx/", "wikidata": None, "place_ids": rmatch([city], "MX") if city else [],
      "source_url": SRC, "source_kind": "official", "site_policy": "robots_allowed", "retrieved_at": now, "license": "public-sector-information (transparency obligation)",
      "source_sha256": sha, "sources": [{"source_url": SRC, "site_policy": "robots_allowed", "source_kind": "official"}],
      "record_note": "Directorio Oficial CJJ (PDF)", "needs_review": city is None})
    if jname:
        nm = re.sub(r"^(Lic|Mtra|Mtro|Dra|Dr|L\.?\w*)\.?\s+", "", jname).strip(); jid = f"{cid}-{slug(nm)}"
        if jid not in jids:
            jids.add(jid); judges.append({"judge_id": jid, "court_id": cid, "name": nm, "title": title, "position_type": "judge", "term_start": None, "term_end": None,
              "status": "sitting", "roster_url": SRC, "source_url": SRC, "site_policy": "robots_allowed", "retrieved_at": now, "needs_review": True,
              "extraction": "CJJ Directorio Oficial PDF; name+title only", "license": "public-sector-information"})
for p, rs in ((CO, courts), (JO, judges)):
    with open(p, "a") as f:
        for r in rs: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("courts", len(courts), "placed", sum(bool(r["place_ids"]) for r in courts), "judges", len(judges), "parent", parent)
