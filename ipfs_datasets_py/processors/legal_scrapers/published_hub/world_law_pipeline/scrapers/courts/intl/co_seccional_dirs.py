"""CO: juzgados from Rama Judicial seccional directory PDFs on ramajudicial.gov.co (Atlántico 'Directorio despachos seccional',
La Guajira 'Directorio nombres y correos'). Court name, municipality, public phone/address. E-mails and judge names NOT stored."""
import json, sys, re, datetime, hashlib, subprocess
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_common import *
RAW = f"{ROOT}/rules/raw/co_dirs"; OUT = f"{ROOT}/data/co/co_courthouses.jsonl"
SRC = {"atlantico": "https://www.ramajudicial.gov.co/documents/2298212/2413828/DIRECTORIO+DESPACHOS+SECCIONAL+ATL%C3%81NTICO.pdf/c168b8db-224b-45da-8bc3-4931848798c0",
       "guajira": "https://www.ramajudicial.gov.co/documents/6065202/40044734/DIRECTORIO+NOMBRES+Y+CORREOS+ELECTRONICOS+DESPACHOS+JUDICIALES+GUAJIRA+4.pdf/4b3d5b9f-509b-4f38-9f02-facb10f07d09"}
rows = [json.loads(l) for l in open(OUT)]; ids = {r["court_id"] for r in rows}; seen = {norm(r["name"]) for r in rows} | {norm(r["name"]+" "+((r.get("address") or {}).get("city") or "")) for r in rows}
POL = "robots_disallowed_user_authorized_2026-10-29;terms:ramajudicial.gov.co portal terms (public info, attribution; Ley 23/1982 art.41, Ley 1712/2014)"
now = datetime.datetime.now(datetime.UTC).isoformat(); new = []
def lv(n):
    n = n.lower()
    if "tribunal" in n: return "appellate"
    if "familia" in n: return "family"
    if "adolescen" in n or "menores" in n: return "juvenile"
    if "administrativ" in n: return "administrative"
    if "municipal" in n or "pequeñas causas" in n or "m/pal" in n: return "trial_limited"
    return "trial_general"
def add(name, city, dep, sub, phone, street, key):
    name = re.sub(r"\s+", " ", name).strip(" .-")
    cid = "co-" + re.sub(r"[^a-z0-9]+", "-", norm(f"{dep} {name}"))[:110].strip("-")
    if cid in ids or norm(name) in seen or norm(name+" "+(city or "")) in seen: return
    ids.add(cid); seen.add(norm(name)); seen.add(norm(name+" "+(city or ""))); raw = open(f"{RAW}/{key}.pdf", "rb").read()
    new.append({"court_id": cid, "record_type": "courthouse", "name": name, "name_local": name, "level": lv(name), "court_system": "national", "country_code": "CO",
      "subdivision": sub, "jurisdiction": city or dep, "parent_court_id": None, "address": {"street": street, "city": city, "postcode": None, "region": dep, "country": "Colombia"},
      "geo": {"lat": None, "lon": None}, "phone": phone, "website": None, "wikidata": None, "place_ids": rmatch([city], "CO") if city else [],
      "source_url": SRC[key], "source_kind": "official", "site_policy": POL, "retrieved_at": now, "license": "Rama Judicial (ramajudicial.gov.co); Ley 23/1982 art. 41",
      "source_sha256": hashlib.sha256(raw).hexdigest(), "sources": [{"source_url": SRC[key], "site_policy": POL, "source_kind": "official"}],
      "record_note": f"seccional directory PDF ({key})", "municipality": city, "needs_review": city is None})
# Atlántico
L = open(f"{RAW}/atlantico.txt", encoding="utf-8").read().split("\n"); cur = None
def fl():
    global cur
    if cur and cur["name"].upper().startswith("JUZGADO"):
        nm = cur["name"].title(); city = "Barranquilla" if re.search(r"barranquilla|bquilla|\bba\b", nm.lower() + " " + cur.get("mail", "")) else None
        m = re.search(r"\bDe ([A-ZÁÉÍÓÚ][\wáéíóúñ ]+)$", nm); city = city or (m.group(1).strip() if m else None)
        add(nm, city, "Atlántico", "CO-ATL", cur.get("tel"), None, "atlantico")
    cur = None
for l in L:
    left = l[:34].strip(); rest = l[34:]
    if re.match(r"^\s*JUZGADO", l) and not re.match(r"^\s*JUZGADOS", l): fl(); cur = {"name": left}
    elif cur is not None:
        if "Rama Judicial" in l or "SIGCMA" in l or "DESPACHO" in l and "CORREO" in l: continue
        if re.match(r"^\s{10,}[A-ZÁÉÍÓÚ ]{8,}$", l): fl(); continue
        if left and not re.search(r"@", left): cur["name"] += " " + left
        m = re.search(r"(\S+@\S+)\s+(\d[\d -]{5,})?", l)
        if m: cur["mail"] = m.group(1); cur["tel"] = (m.group(2) or "").strip() or None
fl()
# Guajira
for l in open(f"{RAW}/guajira.txt", encoding="utf-8"):
    m = re.match(r"^\s*(Juzgado\.?\s.+?)-[A-ZÁÉÍÓÚ][^@]+?\s{2,}\S+@\S+\s+(.+?)\s*$", l)
    if not m: continue
    court = m.group(1).replace("M/pal", "Municipal").replace("P/cuo", "Promiscuo").replace("C/to", "Circuito")
    adr = m.group(2); city = adr.rsplit("-", 1)[-1].strip().title() if "-" in adr else adr.split()[-1].title()
    add(court, city, "La Guajira", "CO-LAG", None, adr, "guajira")
with open(OUT, "a") as f:
    for r in new: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("added", len(new), "placed", sum(bool(r["place_ids"]) for r in new)); [print(" ", r["name"], "|", r["address"]["city"]) for r in new[:5] + new[-4:]]
