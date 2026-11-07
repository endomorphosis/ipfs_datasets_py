"""CO: Dirección Seccional Tunja 'Directorio Despachos Judiciales' HTML table (ramajudicial.gov.co/web/..., robots-allowed; /documents/ is disallowed and not used).
CL: tribunal list (448 courts with corte de apelaciones) from github felipesanma/chile-utils pjud/tribunales.json (no LICENSE file; facts compiled from pjud.cl) -> needs_review."""
import json, sys, re, datetime, hashlib, html, collections
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_common import *
now = datetime.datetime.now(datetime.UTC).isoformat()
def lv(n):
    n = n.lower()
    if "tribunal superior" in n or "corte" in n or "tribunal administrativo" in n: return "appellate"
    if "familia" in n: return "family"
    if "menores" in n or "adolescen" in n: return "juvenile"
    if "administrativo" in n: return "administrative"
    if "municipal" in n or "pequeñas" in n or "policía local" in n: return "trial_limited"
    return "trial_general"
def slug(s): return re.sub(r"[^a-z0-9]+", "-", norm(s))[:110].strip("-")
def run(cc, items, src, pol, lic, note, nr):
    p = f"{ROOT}/data/{cc}/{cc}_courthouses.jsonl"; R = [json.loads(l) for l in open(p)]
    ids = {r["court_id"] for r in R}; seen = {(norm(r["name"]), norm((r.get("address") or {}).get("city") or "")) for r in R}; nm_only = {norm(r["name"]) for r in R}
    new = []
    for it in items:
        k = (norm(it["name"]), norm(it["city"] or ""))
        if it["id"] in ids or k in seen or norm(it["name"]) in nm_only: continue
        ids.add(it["id"]); seen.add(k)
        new.append({"court_id": it["id"], "record_type": "courthouse", "name": it["name"], "name_local": it["name"], "level": lv(it["name"]), "court_system": "national",
          "country_code": cc.upper(), "subdivision": it["sub"], "jurisdiction": it.get("jur"), "parent_court_id": it.get("parent"),
          "address": {"street": it.get("street"), "city": it["city"], "postcode": None, "region": it.get("region"), "country": it["country"]}, "geo": {"lat": None, "lon": None},
          "phone": None, "website": None, "wikidata": None, "place_ids": rmatch([it["city"]], cc.upper()) if it["city"] else [], "source_url": src, "source_kind": it.get("kind", "official"),
          "site_policy": pol, "retrieved_at": now, "license": lic, "source_sha256": it["sha"], "sources": [{"source_url": src, "site_policy": pol, "source_kind": it.get("kind", "official")}],
          "record_note": note + (f"; code {it['code']}" if it.get("code") else ""), "municipality": it["city"], "needs_review": nr or not it["city"]})
    with open(p, "a") as f:
        for r in new: f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(cc, "added", len(new), "placed", sum(bool(r["place_ids"]) for r in new), "of", len(items))
# CO Tunja
raw = open(f"{ROOT}/rules/raw/co_dirs/tunja.html", "rb").read(); t = raw.decode("utf-8", "ignore"); sha = hashlib.sha256(raw).hexdigest(); items = []
for tr in re.findall(r"<tr.*?</tr>", t, re.S):
    td = [html.unescape(re.sub(r"<[^>]+>|\s+", " ", x)).strip() for x in re.findall(r"<td.*?</td>", tr, re.S)]
    if len(td) < 7 or not re.match(r"\d{12}", td[3]): continue
    dist, circ, mun, code, name, _mail, adr = td[:7]
    sub = "CO-CAS" if dist.lower().startswith("yopal") else "CO-BOY"
    items.append({"id": f"co-{code}", "name": name, "city": mun, "sub": sub, "jur": f"Distrito {dist}; Circuito {circ}", "street": adr or None, "region": None, "country": "Colombia", "code": code, "sha": sha})
print("CO districts", collections.Counter(i["jur"].split(";")[0] for i in items))
run("co", items, "https://www.ramajudicial.gov.co/web/direccion-seccional-de-administracion-judicial-de-tunja/directorio-despachos-judiciales", "robots_allowed",
    "Rama Judicial (ramajudicial.gov.co); public information Ley 1712/2014", "Seccional Tunja directorio despachos (HTML)", False)
# CL
raw = open(f"{ROOT}/rules/raw/cl_pjud/tribunales.json", "rb").read(); sha = hashlib.sha256(raw).hexdigest(); items = []
for x in json.loads(raw):
    nm = x["nombre"]; m = re.search(r"\b(?:de|del)\s+([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ' .-]+)$", nm); city = m.group(1).strip() if m else None
    if city and re.search(r"santiago|garantía|letras|trabajo|familia|penal|cobranza", city.lower()) and city.lower() != "santiago": city = None
    items.append({"id": f"cl-pjud-{x['codigo']}", "name": nm, "city": city, "sub": "CL", "jur": f"{x.get('corteNombre')}; competencias: {', '.join(x.get('competencias') or [])}",
      "region": None, "country": "Chile", "code": str(x["codigo"]), "sha": sha, "kind": "secondary"})
run("cl", items, "https://github.com/felipesanma/chile-utils/blob/main/pjud/tribunales.json", "github_public:no_license_file;compiled_from:pjud.cl(robots_allowed)",
    "unspecified (no LICENSE in repo); underlying facts: Poder Judicial de Chile", "chile-utils pjud tribunales (tribunal code + corte de apelaciones)", True)
