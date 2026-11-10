"""AR-X: Córdoba judiciary court buildings (sedes judiciales) from justiciacordoba.gob.ar official page. Capital buildings + one
tribunales building per interior seat. Non-court buildings (MPF, forensic, admin, mediation) excluded. Public phones only."""
import json, sys, re, html, datetime, hashlib
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_common import *
RAW = f"{ROOT}/rules/raw/ar_cba/sedes.html"; SRC = "https://www.justiciacordoba.gob.ar/justiciacordoba/oficinasjudiciales/sedes_judiciales"
OUT = f"{ROOT}/data/ar/ar_courthouses.jsonl"
raw = open(RAW, "rb").read()
try: t = raw.decode("utf-8")
except UnicodeDecodeError: t = raw.decode("cp1252", "ignore")
t = html.unescape(t)
rows = [json.loads(l) for l in open(OUT)]; ids = {r["court_id"] for r in rows}; seen = {norm(r["name"]) for r in rows}
now = datetime.datetime.now(datetime.UTC).isoformat(); new = []
if "ar-x-tsj" not in ids:
    new.append({"court_id": "ar-x-tsj", "record_type": "court_body", "name": "Tribunal Superior de Justicia de la Provincia de Córdoba", "name_local": None, "level": "supreme",
      "court_system": "state", "country_code": "AR", "subdivision": "AR-X", "jurisdiction": "Provincia de Córdoba", "parent_court_id": None,
      "address": {"street": "Caseros 551", "city": "Córdoba", "postcode": None, "region": "Córdoba", "country": "Argentina"}, "geo": {"lat": None, "lon": None},
      "phone": None, "website": "https://www.justiciacordoba.gob.ar/", "wikidata": None, "place_ids": rmatch(["Córdoba"], "AR"), "source_url": SRC, "source_kind": "official",
      "site_policy": "robots_unknown:official", "retrieved_at": now, "license": "public-sector-information", "sources": [{"source_url": SRC, "site_policy": "robots_unknown:official", "source_kind": "official"}],
      "record_note": "hierarchy node"})
CAP = re.compile(r"^(Tribunales|Polo Judicial|Edificio)", re.I); SKIP = re.compile(r"MPF|Polic[ií]a Judicial|Medicina Forense|Administraci[oó]n General|Mediaci[oó]n", re.I)
for h, b in re.findall(r"<h4[^>]*>(.*?)</h4>(.*?)(?=<h4|\Z)", t, re.S):
    h = re.sub(r"<[^>]+>|\s+", " ", h).strip(); body = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", b)).strip()
    if not h or SKIP.search(h): continue
    capital = bool(CAP.match(h)); city = "Córdoba" if capital else h
    name = h if capital else f"Tribunales de {h}"
    street = re.split(r"\s\(?0\d{2,4}\)?|\s3541", body)[0].strip(" ,")
    phone = (re.search(r"(\(?0?\d{3,4}\)?[\s–-]*\d[\d\s/–-]{5,})", body) or [None, None])[1]
    cid = "ar-x-" + re.sub(r"[^a-z0-9]+", "-", norm(name)).strip("-")
    if cid in ids or norm(name) in seen: continue
    ids.add(cid); seen.add(norm(name))
    new.append({"court_id": cid, "record_type": "courthouse", "name": name, "name_local": name, "level": "trial_general" if not re.search(r"Electoral", h) else "other",
      "court_system": "state", "country_code": "AR", "subdivision": "AR-X", "jurisdiction": "Córdoba (capital)" if capital else f"Sede judicial {h}", "parent_court_id": "ar-x-tsj",
      "address": {"street": street[:150] or None, "city": city, "postcode": None, "region": "Córdoba", "country": "Argentina"}, "geo": {"lat": None, "lon": None},
      "phone": phone.strip() if phone else None, "website": "https://www.justiciacordoba.gob.ar/", "wikidata": None, "place_ids": rmatch([city], "AR"),
      "source_url": SRC, "source_kind": "official", "site_policy": "robots_unknown:official", "retrieved_at": now, "license": "public-sector-information",
      "source_sha256": hashlib.sha256(raw).hexdigest(), "sources": [{"source_url": SRC, "site_policy": "robots_unknown:official", "source_kind": "official"}],
      "record_note": "Poder Judicial de Córdoba sedes judiciales (building-level; houses multiple courts)", "municipality": city})
with open(OUT, "a") as f:
    for r in new: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("added", len(new), "placed", sum(bool(r["place_ids"]) for r in new)); [print(" ", r["name"], "|", r["address"]["street"], "|", r["phone"]) for r in new[:6]]
