"""BR-MG: one fórum (courthouse) row per TJMG comarca from the public Guia Judiciário (www8.tjmg.jus.br/servicos/gj/guia,
robots.txt allows). Stores fórum name, address, CEP, public phone, entrância, installation date. Staff e-mails not stored."""
import json, sys, re, html, glob, os, datetime, hashlib
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_common import *
RAW = f"{ROOT}/rules/raw/br_tjmg"; OUT = f"{ROOT}/data/br/br_courthouses.jsonl"
U = "https://www8.tjmg.jus.br/servicos/gj/guia/primeira_instancia/consulta.do?codigoComposto=MG_{c}&codigoMunp={c}&linesByPage=10&opcConsulta=1"
rows = [json.loads(l) for l in open(OUT)]; ids = {r["court_id"] for r in rows}
seen = {(norm(r["name"]), norm((r.get("address") or {}).get("city") or "")) for r in rows}
tj = next((r["court_id"] for r in rows if r["court_id"] == "br-mg-appellate-tjmg"), None)
new = []
for f in sorted(glob.glob(f"{RAW}/[0-9]*.html")):
    c = os.path.basename(f)[:-5]; raw = open(f, "rb").read()
    t = html.unescape(raw.decode("latin-1", "ignore"))
    cells = [re.sub(r"\s+", " ", x).strip() for x in re.sub(r"<[^>]+>", "\x00", t).split("\x00")]
    cells = [x for x in cells if x]
    try: i = cells.index("Resultado da Busca pelo Fórum do Município")
    except ValueError: continue
    w = cells[i + 1:i + 30]
    hdr = w[0]; comarca = re.sub(r"^\d+\s+", "", hdr)
    def after(k):
        return w[w.index(k) + 1] if k in w and w.index(k) + 1 < len(w) else None
    ent = after("Entrancia:"); inst = after("Data de Instalação da Comarca:")
    j = w.index("Data de Instalação da Comarca:") + 2 if "Data de Instalação da Comarca:" in w else 1
    forum = w[j]; rest = w[j + 1:]
    street = next((x for k, x in enumerate(rest) if k > 0 and rest[k - 1].startswith(comarca) is False and re.search(r"\d", x) and not x.endswith(":") and "(" not in x), None)
    tel = after("Telefones:"); cep = after("CEP:")
    city = next((x[:-5] for x in rest if x.endswith(" - MG")), comarca)
    if not re.search(r"f[óo]rum|foro|palácio", forum.lower()): forum = f"Fórum da Comarca de {comarca}"
    cid = f"br-mg-tjmg-forum-{c}"
    if cid in ids or (norm(forum), norm(city)) in seen: continue
    seen.add((norm(forum), norm(city)))
    new.append({"court_id": cid, "record_type": "courthouse", "name": forum, "name_local": forum, "level": "trial_general", "court_system": "state",
      "country_code": "BR", "subdivision": "BR-MG", "jurisdiction": f"Comarca de {comarca}", "parent_court_id": tj,
      "address": {"street": street, "city": city, "postcode": cep, "region": "Minas Gerais", "country": "Brasil"}, "geo": {"lat": None, "lon": None},
      "phone": tel if tel and not tel.endswith(":") else None, "website": "https://www.tjmg.jus.br/", "wikidata": None, "place_ids": rmatch([city, comarca], "BR"),
      "source_url": U.format(c=c), "source_kind": "official", "site_policy": "robots_allowed",
      "retrieved_at": datetime.datetime.fromtimestamp(os.path.getmtime(f), datetime.UTC).isoformat(), "license": "public-sector-information",
      "source_sha256": hashlib.sha256(raw).hexdigest(), "sources": [{"source_url": U.format(c=c), "site_policy": "robots_allowed", "source_kind": "official"}],
      "record_note": f"TJMG Guia Judiciário; entrância {ent}; comarca instalada {inst}", "municipality": city})
if "--dry" in sys.argv:
    for r in new[:3]: print(json.dumps(r, ensure_ascii=False)[:600])
    print("would add", len(new)); sys.exit()
with open(OUT, "a") as f:
    for r in new: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("added", len(new), "placed", sum(bool(r["place_ids"]) for r in new), "parent", tj)
