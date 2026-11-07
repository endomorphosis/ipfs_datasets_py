"""MX-CMX: Poder Judicial CDMX court buildings from official 'Ubicaciones' page (poderjudicialcdmx.gob.mx/ubicaciones/; robots allows).
Archives, forensic institute and mediation centre excluded. Reclusorio buildings = seats of penal courts."""
import json, sys, re, html, datetime, hashlib
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_common import *
RAW = f"{ROOT}/rules/raw/mx_cdmx/ubic.html"; SRC = "https://poderjudicialcdmx.gob.mx/ubicaciones/"; OUT = f"{ROOT}/data/mx/mx_courthouses.jsonl"
raw = open(RAW, "rb").read(); s = re.sub(r"\n\s*\n+", "\n", re.sub(r"<[^>]+>", "\n", html.unescape(raw.decode("utf-8", "ignore"))))
rows = [json.loads(l) for l in open(OUT)]; ids = {r["court_id"] for r in rows}; seen = {norm(r["name"]) for r in rows}
par = next((r["court_id"] for r in rows if r.get("subdivision") in ("MX-CMX", "MX-DIF") and r.get("record_type") == "court_body"), None)
now = datetime.datetime.now(datetime.UTC).isoformat(); new = []
for m in re.finditer(r"([^\n]+)\n([^\n]*C\.P\.[^\n]*)", s):
    h, adr = m.group(1).strip().rstrip("."), m.group(2).strip()
    if re.search(r"Archivo|Forenses|Justicia Alternativa|Ubicación Ciudad", h): continue
    name = f"Juzgados Penales – {h}" if h.startswith("Reclusorio") else f"Poder Judicial CDMX – Inmueble {h}"
    alc = (re.search(r"Alcald[ií]a\.?\s*([^,]+)", adr) or [None, None])[1]; cp = (re.search(r"C\.P\.\s*(\d{5})", adr) or [None, None])[1]
    cid = "mx-cmx-pj-" + re.sub(r"[^a-z0-9]+", "-", norm(h)).strip("-")
    if cid in ids or norm(name) in seen: continue
    ids.add(cid); seen.add(norm(name))
    new.append({"court_id": cid, "record_type": "courthouse", "name": name, "name_local": name, "level": "trial_general", "court_system": "state",
      "country_code": "MX", "subdivision": "MX-CMX", "jurisdiction": "Ciudad de México", "parent_court_id": par,
      "address": {"street": adr.split(", C.P.")[0], "city": "Ciudad de México", "postcode": cp, "region": "Ciudad de México", "country": "México"},
      "geo": {"lat": None, "lon": None}, "phone": None, "website": "https://poderjudicialcdmx.gob.mx/", "wikidata": None,
      "place_ids": rmatch([alc], "MX") if alc else [], "source_url": SRC, "source_kind": "official", "site_policy": "robots_allowed", "retrieved_at": now,
      "license": "public-sector-information", "source_sha256": hashlib.sha256(raw).hexdigest(),
      "sources": [{"source_url": SRC, "site_policy": "robots_allowed", "source_kind": "official"}],
      "record_note": "PJCDMX building (houses multiple salas/juzgados); level approximate", "municipality": alc, "needs_review": True})
with open(OUT, "a") as f:
    for r in new: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("added", len(new), "placed", sum(bool(r["place_ids"]) for r in new), "parent", par)
