"""DO: Poder Judicial 'Directorio Judicial' (directoriojudicial.poderjudicial.gob.do, official SPA 'para consultar tribunales y salas judiciales').
The SPA's public, unauthenticated JSON endpoint (apiUrl in its /config.js; no key/token involved) /api/directorio/salas returns all 709 salas with
tribunal, instance, judicial department/district, street address, court switchboard phone, coordinates and presiding judge (juez titular).
Rows: one courthouse per tribunal (404); judges = juez titular names not already in the 717-judge official roster (do_pj_jueces.py), needs_review.
No staff data stored. robots.txt on the SPA host returns the SPA shell (no robots policy) -> robots_absent."""
import json, os, re, sys, time, hashlib, datetime, unicodedata, requests
ROOT = "/workspace/world_courts"; SD = f"{ROOT}/state/run_20261031_06/do"; os.makedirs(SD, exist_ok=True)
API = "https://apidirectoriojudicial.azurewebsites.net/api/directorio/salas"; SPA = "https://directoriojudicial.poderjudicial.gob.do/"
now = datetime.datetime.now(datetime.UTC).isoformat(); RAWP = f"{SD}/salas_all.json"
if not os.path.exists(RAWP):
    allr, p = [], 1
    while True:
        d = requests.get(API, params={"page": p, "pageSize": 100, "idTipoTribunal": 1}, headers={"User-Agent": "WorldCourtsResearchBot/1.0"}, timeout=60).json()
        allr += d["items"]
        if not d.get("hasNext"): break
        p += 1; time.sleep(3)
    json.dump(allr, open(RAWP, "w"), ensure_ascii=False)
S = json.load(open(RAWP)); sha = hashlib.sha256(open(RAWP, "rb").read()).hexdigest()
LEVEL = {"SUPREMA CORTE DE JUSTICIA": "supreme", "CORTE DE APELACION Y EQUIVALENTES": "appeal", "PRIMERA INSTANCIA Y EQUIVALENTES": "first_instance", "JUZGADO DE PAZ Y EQUIVALENTES": "limited_jurisdiction"}
SMALL = {"de", "del", "la", "las", "los", "y", "en", "e"}
def tc(s): return " ".join(w.lower() if (w.lower() in SMALL and i) else w.capitalize() for i, w in enumerate((s or "").split()))
pol = "robots_absent (official SPA public JSON endpoint, unauthenticated; no key used)"; lic = "Poder Judicial de la República Dominicana, Directorio Judicial (official public directory); facts, no licence stated"
byt = {}
for s in S: byt.setdefault(s["idTribunal"], []).append(s)
CO = f"{ROOT}/data/do/do_courthouses.jsonl"; old = [json.loads(l) for l in open(CO)]
oid = {r["court_id"] for r in old}; oname = {re.sub(r"\s+", " ", (r.get("name") or "").lower()): r["court_id"] for r in old}; cmap = {}
crow = []
for tid, ss in sorted(byt.items()):
    s0 = sorted(ss, key=lambda x: x["sala"].startswith("PRESIDENCIA"))[0]
    name = tc(s0["nombreTribunal"]); cid = f"do-pjdir-{tid}"
    if name.lower() in oname: cmap[tid] = oname[name.lower()]; continue
    if cid in oid: continue
    mats = sorted({m.strip() for x in ss for m in (x.get("materias") or "").split(",") if m.strip()})
    crow.append({"court_id": cid, "record_type": "courthouse", "name": name, "name_local": s0["nombreTribunal"], "level": LEVEL.get(s0["instancia"], "other"),
        "court_system": "national", "country_code": "DO", "subdivision": tc(s0["departamento"]), "jurisdiction": f"Distrito Judicial {tc(s0['distrito'])}",
        "parent_court_id": None, "address": {"street": tc(s0["direccion"]) if s0.get("direccion") else None, "city": None, "postcode": None,
        "region": tc(s0["distrito"]), "country": "República Dominicana"}, "geo": {"lat": s0["x"], "lon": s0["y"]}, "geo_source": "official directory coordinates",
        "phone": s0.get("telefono"), "website": SPA, "wikidata": None, "place_ids": [], "source_url": f"{API}?idTribunal={tid}", "source_kind": "official",
        "site_policy": pol, "retrieved_at": now, "license": lic, "source_sha256": sha,
        "sources": [{"source_url": SPA, "site_policy": pol, "source_kind": "official"}], "court_code": s0.get("codigoTribunal"), "instance_local": s0["instancia"],
        "subject_matters": mats, "salas": sorted({tc(x["sala"]) for x in ss}), "record_note": "official Directorio Judicial tribunal entry; phone is the court's public number", "needs_review": False})
with open(CO, "a") as f:
    for r in crow: f.write(json.dumps(r, ensure_ascii=False) + "\n")
# judges
def toks(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return [t for t in re.findall(r"[a-z]+\.?", s) if not t.endswith(".") and len(t) > 1 and t not in ("de", "del", "la", "los", "las")]
JO = f"{ROOT}/data/do/do_judges.jsonl"; J = [json.loads(l) for l in open(JO)]; js = [set(toks(x["name"])) for x in J]; jid = {x["judge_id"] for x in J}
jrow = []
for s in S:
    nm = (s.get("juezTitular") or "").strip()
    if not nm or s["sala"].startswith("PRESIDENCIA"): continue
    t = set(toks(nm))
    if not t or any(t <= x for x in js): continue
    rid = "do-pjdir-" + re.sub(r"[^a-z0-9]+", "-", " ".join(toks(nm))).strip("-") + f"-{s['idTribunal']}"
    if rid in jid: continue
    jid.add(rid); js.append(t)
    jrow.append({"judge_id": rid, "court_id": cmap.get(s["idTribunal"], f"do-pjdir-{s['idTribunal']}"), "name": nm, "title": f"Juez(a) titular, {tc(s['sala'])}", "position_type": "presiding",
        "term_start": None, "term_end": None, "status": "sitting", "roster_url": SPA, "source_url": f"{API}?idTribunal={s['idTribunal']}", "site_policy": pol,
        "retrieved_at": now, "needs_review": True, "extraction": "juezTitular field of the official Directorio Judicial (names often abbreviated; may match a roster entry spelled in full)",
        "license": lic, "source_sha256": sha})
with open(JO, "a") as f:
    for r in jrow: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("courthouses added", len(crow), "judges added", len(jrow))
