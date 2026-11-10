"""BR-PR: TJPR judicial units by comarca from the official CEVID page 'Unidades Judiciais - Comarcas'
(www.tjpr.jus.br/web/cevid/unidades-judiciais-comarcas; robots allows). Unit name, seção judiciária, address, CEP, phone.
Unit e-mails/personal addresses not stored. Dedup by name+city."""
import json, sys, re, html, datetime, hashlib
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_common import *
RAW = f"{ROOT}/rules/raw/br_tjpr/cevid.html"; SRC = "https://www.tjpr.jus.br/web/cevid/unidades-judiciais-comarcas"
OUT = f"{ROOT}/data/br/br_courthouses.jsonl"
raw = open(RAW, "rb").read(); t = html.unescape(raw.decode("utf-8", "ignore"))
paras = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", p)).strip() for p in re.findall(r"<p[^>]*>(.*?)</p>", t, re.S)]
rows = [json.loads(l) for l in open(OUT)]; ids = {r["court_id"] for r in rows}
seen = {(norm(r["name"]), norm((r.get("address") or {}).get("city") or "")) for r in rows}
now = datetime.datetime.now(datetime.UTC).isoformat(); sha = hashlib.sha256(raw).hexdigest()
new = []; comarca = None; unit = None; cur = None
def flush():
    global cur
    if cur and cur.get("addr"):
        m = re.match(r"(.*?)\s*-\s*([^-]+?)\s*-\s*CEP:?\s*([\d.-]+)", cur["addr"])
        street, city, cep = (m.group(1), m.group(2).strip(), m.group(3)) if m else (cur["addr"], comarca.title() if comarca else None, None)
        name = f"{cur['unit'].title()} - Comarca de {comarca.title()}" if cur.get("unit") else f"Fórum da Comarca de {comarca.title()}"
        k = (norm(name), norm(city or ""))
        cid = "br-pr-tjpr-" + re.sub(r"[^a-z0-9]+", "-", norm(name))[:90].strip("-")
        if k not in seen and cid not in ids:
            seen.add(k); ids.add(cid); nl = name.lower()
            lvl = "family" if "família" in nl and "criminal" not in nl else "juvenile" if nl.startswith("vara da infância") else "trial_limited" if nl.startswith("juizado") else "trial_general"
            new.append({"court_id": cid, "record_type": "courthouse", "name": name, "name_local": name, "level": lvl, "court_system": "state",
              "country_code": "BR", "subdivision": "BR-PR", "jurisdiction": f"Comarca de {comarca.title()}" + (f"; {cur['sec']}" if cur.get("sec") else ""),
              "parent_court_id": "br-pr-appellate-tjpr", "address": {"street": street, "city": city, "postcode": cep, "region": "Paraná", "country": "Brasil"},
              "geo": {"lat": None, "lon": None}, "phone": (cur.get("tel") or "")[:120] or None, "website": cur.get("site"), "wikidata": None,
              "place_ids": rmatch([city, comarca], "BR"), "source_url": SRC, "source_kind": "official", "site_policy": "robots_allowed", "retrieved_at": now,
              "license": "public-sector-information", "source_sha256": sha, "sources": [{"source_url": SRC, "site_policy": "robots_allowed", "source_kind": "official"}],
              "record_note": "TJPR CEVID unidades judiciais por comarca (violence-against-women network page; lists criminal/family/single-court units)", "municipality": city})
    cur = None
for p in paras:
    if not p: continue
    if re.fullmatch(r"[A-ZÁÉÍÓÚÂÊÔÃÕÇ' -]{3,60}", p) and not re.match(r"(VARA|JUIZO|JUÍZO|JUIZADO)", p) and len(p) > 1:
        flush(); comarca = p; unit = None; continue
    if re.match(r"^(\d+ª )?(VARA|JUIZO|JUÍZO|JUIZADO|SEÇÃO|CENTRO|NÚCLEO)", p) and p.isupper():
        flush(); cur = {"unit": p}; continue
    if p.startswith("Seção Judiciária:"):
        if cur is None or cur.get("addr"): flush(); cur = {"unit": None}
        cur["sec"] = p.split(":", 1)[1].strip()
    elif p.startswith("Endereço:"):
        if cur is None: cur = {"unit": None}
        cur["addr"] = p.split(":", 1)[1].strip()
    elif p.startswith("Telefone:") and cur: cur["tel"] = p.split(":", 1)[1].strip()
    elif p.startswith("Site:") and cur: cur["site"] = p.split(":", 1)[1].strip() or None
flush()
with open(OUT, "a") as f:
    for r in new: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("added", len(new), "placed", sum(bool(r["place_ids"]) for r in new))
