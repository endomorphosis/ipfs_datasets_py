"""AR-B: Buenos Aires province courts (organismos) from SCBA 'Mapa Judicial Interactivo' (www.scba.gov.ar/guia/mapadeptos.asp,
robots Allow /). One row per organismo: name, fuero, asiento/partido, street, CP, public phone. Judges/staff and e-mails not stored."""
import json, sys, re, html, glob, os, datetime, hashlib, urllib.parse
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_common import *
OUT = f"{ROOT}/data/ar/ar_courthouses.jsonl"; RAW = f"{ROOT}/rules/raw/ar_scba"
rows = [json.loads(l) for l in open(OUT)]; ids = {r["court_id"] for r in rows}; seen = {norm(r["name"]) for r in rows}
now = datetime.datetime.now(datetime.UTC).isoformat(); new = []
if "ar-b-scba" not in ids:
    new.append({"court_id": "ar-b-scba", "record_type": "court_body", "name": "Suprema Corte de Justicia de la Provincia de Buenos Aires", "name_local": None,
      "level": "supreme", "court_system": "state", "country_code": "AR", "subdivision": "AR-B", "jurisdiction": "Provincia de Buenos Aires", "parent_court_id": None,
      "address": {"street": "Avenida 13 entre 47 y 48", "city": "La Plata", "postcode": "1900", "region": "Buenos Aires", "country": "Argentina"}, "geo": {"lat": None, "lon": None},
      "phone": None, "website": "https://www.scba.gov.ar/", "wikidata": None, "place_ids": rmatch(["La Plata"], "AR"), "source_url": "https://www.scba.gov.ar/guia/",
      "source_kind": "official", "site_policy": "robots_allowed", "retrieved_at": now, "license": "public-sector-information",
      "sources": [{"source_url": "https://www.scba.gov.ar/guia/", "site_policy": "robots_allowed", "source_kind": "official"}], "record_note": "hierarchy node"}); ids.add("ar-b-scba")
def lv(n, fuero):
    n = n.lower()
    if "cámara" in n or "casación" in n: return "appellate"
    if "paz" in n: return "trial_limited"
    if "familia" in n: return "family"
    if "joven" in n or "juvenil" in n or "menores" in n: return "juvenile"
    if "contencioso" in n: return "administrative"
    if re.search(r"juzgado|tribunal", n): return "trial_general"
    return "other"
for f in sorted(glob.glob(f"{RAW}/*.html")):
    raw = open(f, "rb").read(); t = html.unescape(raw.decode("latin-1", "ignore"))
    dep = os.path.basename(f)[:-5].replace("_", " ")
    src = "https://www.scba.gov.ar/guia/mapadeptos.asp?depto=" + urllib.parse.quote(dep)
    cells = [re.sub(r"\s+", " ", x).strip() for x in re.sub(r"<[^>]+>", "\x00", t).split("\x00")]; cells = [x for x in cells if x]
    for i, c in enumerate(cells):
        if c != "Generar Qr": continue
        name = cells[i - 1]; w = cells[i + 1:i + 40]
        def g(k):
            return w[w.index(k) + 1] if k in w and w.index(k) + 1 < len(w) else None
        if "Asiento:" not in w: continue
        fuero = g("Fuero:"); asiento = g("Asiento:") or ""
        city = asiento.split(" - ")[0].strip().title(); partido = (re.search(r"Partido:\s*([^-]+)", asiento) or [None, ""])[1].strip().title()
        street = " ".join(x for x in [g("Calle:"), g("Nro:")] if x and not x.endswith(":")); cp = g("CP:")
        tel = " ".join(x for x in [g("Telediscado:"), g("Tel:")] if x and not x.endswith(":")) or None
        cid = "ar-b-" + re.sub(r"[^a-z0-9]+", "-", norm(name))[:100].strip("-")
        if cid in ids or norm(name) in seen: continue
        ids.add(cid); seen.add(norm(name))
        new.append({"court_id": cid, "record_type": "courthouse", "name": name, "name_local": name, "level": lv(name, fuero), "court_system": "state",
          "country_code": "AR", "subdivision": "AR-B", "jurisdiction": f"Departamento Judicial {dep}", "parent_court_id": "ar-b-scba",
          "address": {"street": street or None, "city": city, "postcode": cp if cp and not cp.endswith(":") else None, "region": "Buenos Aires", "country": "Argentina"},
          "geo": {"lat": None, "lon": None}, "phone": tel, "website": "https://www.scba.gov.ar/guia/", "wikidata": None, "place_ids": rmatch([partido, city], "AR"),
          "source_url": src, "source_kind": "official", "site_policy": "robots_allowed", "retrieved_at": now, "license": "public-sector-information",
          "source_sha256": hashlib.sha256(raw).hexdigest(), "sources": [{"source_url": src, "site_policy": "robots_allowed", "source_kind": "official"}],
          "record_note": f"SCBA guía judicial; fuero {fuero}", "municipality": partido or city, "needs_review": lv(name, fuero) == "other"})
with open(OUT, "a") as f:
    for r in new: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("added", len(new), "placed", sum(bool(r["place_ids"]) for r in new))
