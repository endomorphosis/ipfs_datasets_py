"""BR-SP: TJSP court buildings (fóruns/foros/prédios) from the public Lista Telefônica (www.tjsp.jus.br/ListaTelefonica,
ObterImovel endpoint used by that page; robots.txt does not disallow it). Stores name, address, public phone, comarca,
circunscrição, entrância, hours. Administrative contact persons are NOT stored. Dedup by normalized name+city."""
import json, sys, re, html, glob, os, datetime, hashlib
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_common import *
RAW = f"{ROOT}/rules/raw/br_tjsp"; OUT = f"{ROOT}/data/br/br_courthouses.jsonl"
rows = [json.loads(l) for l in open(OUT)]; ids = {r["court_id"] for r in rows}
seen = {(norm(r["name"]), norm((r.get("address") or {}).get("city") or "")) for r in rows}
tj = next((r["court_id"] for r in rows if r["court_id"].startswith("br-sp") and "Justiça do Estado de São Paulo" in r["name"]), "br-sp-appellate-tjsp")
def field(t, k):
    m = re.search(rf"\n{k}\n([^\n]+)", t); return m.group(1).strip() if m else None
new = []
for f in sorted(glob.glob(f"{RAW}/*.html"), key=lambda x: int(os.path.basename(x)[:-5])):
    raw = open(f, encoding="utf-8", errors="ignore").read()
    t = re.sub(r"\n\s*\n+", "\n", re.sub(r"<[^>]+>", "\n", html.unescape(raw)))
    lines = [x.strip() for x in t.split("\n") if x.strip()]
    if len(lines) < 3 or "Localização" not in lines: continue
    name = lines[0]; code = os.path.basename(f)[:-5]
    i = lines.index("Endereço") if "Endereço" in lines else -1
    addr = lines[i + 1] if i >= 0 else ""
    m = re.match(r"(.*?)\s*-\s*CEP\s*([\d-]+)\s*-\s*(.+?)\s*-\s*SP$", addr)
    street, cep, city = (m.group(1), m.group(2), m.group(3)) if m else (addr or None, None, None)
    j = lines.index("Telefone") if "Telefone" in lines else -1
    phone = lines[j + 1].rstrip(";").strip() if j >= 0 and "Informado" not in lines[j + 1] else None
    comarca, circ, ent = field(t, "Comarca"), field(t, "Circunscrição Judiciária"), field(t, "Entrância")
    city = city or field(t, "Município")
    k = (norm(name), norm(city or ""))
    cid = f"br-sp-tjsp-imovel-{code}"
    if k in seen or cid in ids: continue
    seen.add(k)
    nl = name.lower()
    lvl = "appellate" if re.search(r"tribunal|2[ºo] grau|palácio da justiça|segunda inst", nl) else "trial_limited" if "juizado" in nl else "trial_general" if re.search(r"f[óo]rum|foro|anexo|vara", nl) else "other"
    hrs = None
    if "Horário de Atendimento" in lines:
        h = lines.index("Horário de Atendimento"); hrs = "; ".join(lines[h + 1:h + 15:2][:6])
    new.append({"court_id": cid, "record_type": "courthouse", "name": name, "name_local": name, "level": lvl, "court_system": "state",
      "country_code": "BR", "subdivision": "BR-SP", "jurisdiction": f"Comarca de {comarca}" if comarca else None, "parent_court_id": tj,
      "address": {"street": street, "city": city, "postcode": cep, "region": "São Paulo", "country": "Brasil"}, "geo": {"lat": None, "lon": None},
      "phone": phone, "website": "https://www.tjsp.jus.br/ListaTelefonica", "wikidata": None,
      "place_ids": rmatch([city, comarca], "BR"), "source_url": f"https://www.tjsp.jus.br/ListaTelefonica/ObterImovel?codigo={code}",
      "source_kind": "official", "site_policy": "robots_allowed", "retrieved_at": datetime.datetime.fromtimestamp(os.path.getmtime(f), datetime.UTC).isoformat(),
      "license": "public-sector-information", "source_sha256": hashlib.sha256(raw.encode()).hexdigest(), "hours": hrs,
      "sources": [{"source_url": "https://www.tjsp.jus.br/ListaTelefonica", "site_policy": "robots_allowed", "source_kind": "official"}],
      "record_note": f"TJSP imóvel {code}; circunscrição {circ}; entrância {ent}", "municipality": city, "needs_review": lvl == "other"})
with open(OUT, "a") as f:
    for r in new: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("added", len(new), "placed", sum(bool(r["place_ids"]) for r in new), "parent", tj)
