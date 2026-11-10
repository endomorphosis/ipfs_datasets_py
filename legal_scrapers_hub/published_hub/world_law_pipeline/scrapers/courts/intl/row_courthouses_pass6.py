"""Depth-pass-6 sub-national courthouses for thin countries (non-US), linked to global_municipalities place ids.
FR: DILA 'Annuaire de l'administration' open data (api-lannuaire.service-public.fr, Opendatasoft API, Licence Ouverte 2.0); court-office pivots only;
    staff (affectation_personne) never requested.
usage: row_courthouses_pass6.py CC.."""
import sys, json, time, urllib.parse
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_common import *
def merge_into(cc, new):
    p = f"{ROOT}/data/{cc}/{cc}_courthouses.jsonl"; old = rjl(p)
    bodies = [r for r in old if r.get("record_type") == "court_body"]; ch = [r for r in old if r.get("record_type") != "court_body"]
    ids = {r["court_id"] for r in old}; uniq = []
    for r in new:
        b = r["court_id"]; i = 2
        while r["court_id"] in ids: r["court_id"] = f"{b}-{i}"; i += 1
        ids.add(r["court_id"]); uniq.append(r)
    allr, dup, add = merge_dedupe(ch, uniq)
    wjl(p, bodies + allr); print(cc, "new", len(new), "dupes", dup, "added", add, flush=True)
def place(cc, city, lat, lon, extra=()):
    ids = rmatch([city, *extra], cc)
    if ids: return ids[:1], "commune_name"
    if lat is not None:
        c = nearest_city(lat, lon, cc)
        if c:
            ids = rmatch([c[2]], cc)
            if ids: return ids[:1], "geonames_nearest_city_name"
    return [], None
FR_API = "https://api-lannuaire.service-public.fr/api/explore/v2.1/catalog/datasets/api-lannuaire-administration/records"
FR_PIV = {"tgi": ("ordinary", "general", "fr-ordinary-general"), "ti": ("ordinary", "limited", "fr-ordinary-limited"), "te": ("ordinary", "limited", "fr-ordinary-limited"),
          "prudhommes": ("labour", "general", "fr-labour-general"), "tribunal_commerce": ("commercial", "general", "fr-commercial-general"),
          "cour_appel": ("ordinary", "appellate", "fr-ordinary-appellate"), "ta": ("administrative", "general", "fr-administrative-general"), "caa": ("administrative", "appellate", "fr-administrative-appellate")}
def fr():
    out = []
    for piv, (fam, tier, parent) in FR_PIV.items():
        off = 0
        while True:
            q = urllib.parse.urlencode({"limit": 100, "offset": off, "where": f'pivot like "{piv}"', "select": "id,nom,pivot,code_insee_commune,adresse,telephone,adresse_courriel,site_internet,url_service_public"})
            js = json.loads(get(FR_API + "?" + q, delay=2.0)); res = js.get("results", [])
            for x in res:
                pv = [p for p in json.loads(x["pivot"] or "[]") if p.get("type_service_local") == piv]
                if not pv: continue
                a = (json.loads(x["adresse"] or "[]") or [{}])[0]
                lat = float(a["latitude"]) if a.get("latitude") else None; lon = float(a["longitude"]) if a.get("longitude") else None
                city = (a.get("nom_commune") or "").title() or None; pids, how = place("FR", city, lat, lon)
                tel = (json.loads(x["telephone"]) or [{}])[0].get("valeur") if x.get("telephone") else None
                web = (json.loads(x["site_internet"]) or [{}])[0].get("valeur") if x.get("site_internet") else None
                out.append(rec(court_id="fr-" + slug(x["nom"]), name=x["nom"], level=tier, court_system=fam, country_code="FR", jurisdiction="FR", parent_court_id=parent,
                    address={"street": a.get("numero_voie") or None, "city": city, "postcode": a.get("code_postal") or None, "region": None, "country": "FR"},
                    geo={"lat": lat, "lon": lon}, phone=tel, website=web, place_ids=pids, place_match_method=how, insee_commune=x.get("code_insee_commune"),
                    court_family=fam, tier=tier, source_url=x.get("url_service_public") or FR_API, source_kind="official", site_policy="open_api_documented",
                    license="Annuaire de l'administration (DILA), Licence Ouverte / Open Licence 2.0", email=x.get("adresse_courriel") or None, annuaire_id=x["id"], annuaire_pivot=piv))
            off += 100
            if off >= js.get("total_count", 0) or not res: break
        print(piv, len(out), flush=True)
    return out
B = {"FR": fr}
def fill_places(cc):
    p = f"{ROOT}/data/{cc}/{cc}_courthouses.jsonl"; R = rjl(p); n = 0
    for r in R:
        if r.get("record_type") == "court_body" or r.get("place_ids"): continue
        g = r.get("geo") or {}; ids, how = place(cc.upper(), (r.get("address") or {}).get("city"), g.get("lat"), g.get("lon"))
        if ids: r["place_ids"] = ids; r["place_match_method"] = how; n += 1
    wjl(p, R); print(cc, "place_ids filled", n)

if __name__ == "__main__":
    for cc in sys.argv[1:]:
        if cc.startswith("fill:"): fill_places(cc[5:].lower()); continue
        merge_into(cc.lower(), B[cc]())
