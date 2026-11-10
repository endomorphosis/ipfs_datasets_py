"""BR-SC: one fórum row per TJSC comarca page (www.tjsc.jus.br/comarcas/<slug>, linked from 'Endereços e telefones das comarcas').
Address, CEP, public phone. Chefe de Secretaria (staff) name NOT stored. robots.txt not retrievable (WAF page) -> robots_unknown."""
import json, sys, re, html, glob, os, datetime, hashlib
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_common import *
RAW = f"{ROOT}/rules/raw/br_tjsc"; OUT = f"{ROOT}/data/br/br_courthouses.jsonl"
rows = [json.loads(l) for l in open(OUT)]; ids = {r["court_id"] for r in rows}
seen = {(norm(r["name"]), norm((r.get("address") or {}).get("city") or "")) for r in rows}
par = "br-sc-appellate-tjsc" if "br-sc-appellate-tjsc" in ids else None; new = []
for f in sorted(glob.glob(f"{RAW}/*.html")):
    slug = os.path.basename(f)[:-5]
    if slug == "list": continue
    raw = open(f, "rb").read(); s = re.sub(r"\n\s*\n+", "\n", re.sub(r"<[^>]+>", "\n", html.unescape(raw.decode("utf-8", "ignore"))))
    m = re.search(r"Comarca de ([^\n]+)\n(.*?)\nAbrir todos", s, re.S)
    if not m: continue
    comarca = m.group(1).strip(); block = [x.strip() for x in m.group(2).split("\n") if x.strip()]
    tel = next((x for x in block if re.fullmatch(r"\(\d{2}\)\s*[\d -]+", x)), None)
    adr = next((x for x in block if re.search(r"- SC,?\s*\d{5}-?\d{3}", x)), None)
    street = city = cep = None
    if adr:
        mm = re.match(r"(.*),\s*([^,]+?)\s*-\s*SC,?\s*(\d{5}-?\d{3})", adr)
        if mm: street, city, cep = mm.groups()
    city = city or comarca; name = f"Fórum da Comarca de {comarca}"; cid = f"br-sc-tjsc-forum-{slug}"
    if cid in ids or (norm(name), norm(city)) in seen: continue
    seen.add((norm(name), norm(city))); src = f"https://www.tjsc.jus.br/comarcas/{slug}"
    new.append({"court_id": cid, "record_type": "courthouse", "name": name, "name_local": name, "level": "trial_general", "court_system": "state", "country_code": "BR",
      "subdivision": "BR-SC", "jurisdiction": f"Comarca de {comarca}", "parent_court_id": par,
      "address": {"street": street, "city": city, "postcode": cep, "region": "Santa Catarina", "country": "Brasil"}, "geo": {"lat": None, "lon": None},
      "phone": tel, "website": src, "wikidata": None, "place_ids": rmatch([city, comarca], "BR"), "source_url": src, "source_kind": "official",
      "site_policy": "robots_unknown:official", "retrieved_at": datetime.datetime.fromtimestamp(os.path.getmtime(f), datetime.UTC).isoformat(),
      "license": "public-sector-information", "source_sha256": hashlib.sha256(raw).hexdigest(),
      "sources": [{"source_url": src, "site_policy": "robots_unknown:official", "source_kind": "official"}], "record_note": "TJSC comarca page", "municipality": city})
with open(OUT, "a") as f:
    for r in new: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("added", len(new), "placed", sum(bool(r["place_ids"]) for r in new), "parent", par)
