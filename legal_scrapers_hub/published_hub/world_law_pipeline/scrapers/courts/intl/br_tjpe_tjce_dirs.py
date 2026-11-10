"""BR: TJPE 'Consulta de Comarcas' (fóruns, address, CEP, phone) and TJCE 'Lista completa de contatos' PDF (units, phone, address).
Crawled 2026-10-29 under explicit user authorization (robots disallowed/unknown). E-mails not stored."""
import json, sys, re, datetime, hashlib, html
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_common import *
RAW = f"{ROOT}/rules/raw/auth_crawl_20261029"; OUT = f"{ROOT}/data/br/br_courthouses.jsonl"
AUTH = "robots_disallowed_user_authorized_2026-10-29"
SRC = {"tjpe": ("https://www.tjpe.jus.br/falecomjud/Comarcas/consultacomarca.asp", "tjpe_consulta.html", "BR-PE", "Pernambuco", AUTH + ";terms:tjpe.jus.br portal (public info; Lei 12.527/2011 LAI)"),
       "tjce": ("https://sistemas-internet.tjce.jus.br/internet/contatos/pdf.asp", "tjce_lista.pdf", "BR-CE", "Ceará", AUTH + ";terms:tjce.jus.br portal (public info; Lei 12.527/2011 LAI)")}
rows = [json.loads(l) for l in open(OUT)]; ids = {r["court_id"] for r in rows}
key = lambda n, c: norm(f"{n} {c or ''}")
seen = {key(r["name"], (r.get("address") or {}).get("city")) for r in rows}
now = datetime.datetime.now(datetime.UTC).isoformat(); new = []
def lv(n):
    n = n.lower()
    if "juizado" in n: return "trial_limited"
    if "famil" in n: return "family"
    if "infância" in n or "infancia" in n: return "juvenile"
    if "turma recursal" in n: return "appellate"
    return "trial_general"
def add(src, name, city, street, cep, phone):
    url, fn, sub, uf, pol = SRC[src]
    name = re.sub(r"\s+", " ", name).strip(" .-"); city = city and re.sub(r"\s+", " ", city).strip().title().replace(" De ", " de ").replace(" Do ", " do ").replace(" Da ", " da ").replace(" Dos ", " dos ").replace(" E ", " e ")
    cid = f"br-{sub[-2:].lower()}-" + re.sub(r"[^a-z0-9]+", "-", norm(f"{city or ''} {name}"))[:110].strip("-")
    k = key(name, city)
    if cid in ids or k in seen: return
    ids.add(cid); seen.add(k)
    new.append({"court_id": cid, "record_type": "courthouse", "name": name, "name_local": name, "level": lv(name), "court_system": "state", "country_code": "BR",
      "subdivision": sub, "jurisdiction": city, "parent_court_id": None, "address": {"street": street, "city": city, "postcode": cep, "region": uf, "country": "Brazil"},
      "geo": {"lat": None, "lon": None}, "phone": phone, "website": None, "wikidata": None, "place_ids": rmatch([city], "BR") if city else [],
      "source_url": url, "source_kind": "official", "site_policy": pol, "retrieved_at": now, "license": "public sector information (Lei 12.527/2011)",
      "source_sha256": hashlib.sha256(open(f"{RAW}/{fn}", "rb").read()).hexdigest(), "sources": [{"source_url": url, "site_policy": pol, "source_kind": "official"}],
      "record_note": f"{src} official directory (user-authorized crawl)", "municipality": city, "needs_review": city is None})
# TJPE
s = open(f"{RAW}/tjpe_consulta.html", encoding="latin-1").read()
for m in re.finditer(r'<span class="texto01">\s*([^<]+?) - das [^<]*<a href="consulta2comarca[^"]*"\s*><br>([^<]+)</a>\s*<br>([^<]*)<br>([^<]*)<br>', s):
    city, forum, adr, tel = (html.unescape(x).strip() for x in m.groups())
    cep = re.search(r"Cep:\s*(\d{5})-?(\d{3})", adr); street = re.sub(r"\s*-\s*Cep:.*", "", adr).strip()
    nm = forum if re.search(r"f[oó]rum", forum, re.I) else f"Fórum {forum}"
    add("tjpe", f"{nm} ({city})" if city.lower() not in nm.lower() else nm, city, street or None, f"{cep[1]}-{cep[2]}" if cep else None, re.sub(r"\s+", " ", tel) or None)
# TJCE
blocks = re.split(r"\n\s*\n\s*\n", open(f"{RAW}/tjce.txt", encoding="utf-8").read())
for b in blocks:
    L = [l.strip() for l in b.strip().split("\n") if l.strip()]
    if not L or L[0].startswith(("LISTA", "Atualizada")): continue
    nm = L[0].lstrip("* ").strip()
    if not re.search(r"VARA|JUIZADO|F[OÓ]RUM|COMARCA|TURMA|UNIDADE|N[UÚ]CLEO|CEJUSC", nm): continue
    tel = next((re.search(r"\(\d{2}\)\s*[\d-]+", l)[0] for l in L if l.startswith("Fixo") and re.search(r"\(\d{2}\)", l)), None)
    adr = None
    for i, l in enumerate(L):
        if l.startswith("Endereço:"):
            adr = l[9:].strip()
            if i + 1 < len(L) and not re.match(r"(Balcão|Fixo|E-mail|Celular)", L[i+1]): adr += " " + L[i+1]
    m = re.search(r"COMARCA DE ([A-ZÀ-Ü' ]+?)(?:\s*$|\s*-|\s*\()", nm) or re.search(r" - ([A-ZÀ-Ü' ]+)$", nm)
    city = m.group(1) if m else None
    if not city and adr:
        m2 = re.search(r"([A-ZÀ-Üa-zà-ü' ]+)\s*[-/]\s*CE\b", adr); city = m2.group(1).strip() if m2 else None
    cep = re.search(r"\b(\d{5})-?(\d{3})\b", adr or "")
    add("tjce", nm.title().replace(" Da ", " da ").replace(" De ", " de ").replace(" Do ", " do "), city, adr, f"{cep[1]}-{cep[2]}" if cep else None, tel)
with open(OUT, "a") as f:
    for r in new: f.write(json.dumps(r, ensure_ascii=False) + "\n")
import collections; print("added", collections.Counter(r["subdivision"] for r in new), "placed", sum(bool(r["place_ids"]) for r in new))
for r in new[:3] + new[-3:]: print(" ", r["name"], "|", r["address"]["city"], "|", r["address"]["street"])
