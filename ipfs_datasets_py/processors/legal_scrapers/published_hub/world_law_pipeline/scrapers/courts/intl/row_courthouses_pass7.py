"""Depth-pass-7 courthouses (non-US). PL: dane.gov.pl 'Dane teleadresowe sądów' (Ministry of Justice, CC0; institutional contacts only).
JP: courts.go.jp per-district 管内の裁判所の所在地 pages (official, robots-allowed); municipality→place via Wikidata ja labels of global_municipalities ids."""
import sys, re, csv
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_common import *
from row_courthouses_pass6 import merge_into, place
def pl():
    import openpyxl
    ws = openpyxl.load_workbook(f"{ROOT}/data/ref/pl/tele.xlsx", read_only=True)["Arkusz1"]; rows = list(ws.values); h = [str(x).strip() for x in rows[0]]; out = []
    T = {"SA": "appellate", "SO": "general", "SR": "limited"}
    for v in rows[1:]:
        d = dict(zip(h, v)); n = (d.get("Nazwa sądu") or "").strip(); t = (d.get("Typ") or "").strip()
        if not n or t not in T: continue
        city = (d.get("Miejscowość") or "").strip() or None; pids, how = place("PL", city, None, None)
        out.append(rec(court_id="pl-" + slug(n), name=n, level=T[t], court_system="ordinary", country_code="PL", jurisdiction="PL", parent_court_id="pl-ordinary-" + T[t],
            address={"street": d.get("Ulica"), "city": city, "postcode": d.get("Kod pocztowy"), "region": d.get("Apelacja"), "country": "PL"}, geo={"lat": None, "lon": None},
            phone=str(d.get("Telefon") or "") or None, email=d.get("E-mail"), place_ids=pids, place_match_method=how, court_family="ordinary", tier=T[t],
            appellate_area=d.get("Apelacja"), district_area=d.get("Okręg"), source_url="https://dane.gov.pl/pl/dataset/985", source_kind="official",
            site_policy="open_data_portal", license="CC0 1.0 (dane.gov.pl)"))
    return out
def jp():
    from bs4 import BeautifulSoup
    ja = {}
    for r in csv.DictReader(open("/tmp/jpja.csv")): ja.setdefault(r["l"], "wd:" + r["m"].rsplit("/", 1)[1])
    idx = get("https://www.courts.go.jp/courthouse/map_tel/index.html", delay=2.0)
    urls = sorted(set(re.findall(r'href="\./\.\./\.\./([a-z-]+/about/syozai/index\.html)"', idx))); out = []; seen = set()
    for u in urls:
        url = "https://www.courts.go.jp/" + u
        try: s = BeautifulSoup(get(url, delay=2.0), "html.parser")
        except Exception as e: print("ERR", url, e); continue
        for tr in s.select("table tr"):
            td = [c.get_text(" ", strip=True) for c in tr.find_all("td")]
            if len(td) < 3 or not re.match(r"\d{3}-\d{4}", td[1]): continue
            name = td[0]; addr = td[2].split("(")[0].split("（")[0].strip()
            if name in seen: continue
            seen.add(name); m = re.match(r"(.+?[都道府県])(.+?[市区町村])", addr)
            muni = m.group(2) if m else None; pid = None
            if muni:
                for k in (muni, re.sub(r"^.+?郡", "", muni)):
                    if k in ja: pid = ja[k]; break
            ph = re.search(r"\d{2,5}-\d{1,4}-\d{3,4}", td[-1] if len(td) > 3 else ""); fam = "family" if "家庭" in name.split()[0] else "ordinary"
            tier = "appellate" if "高等" in name else ("limited" if name.split()[0].endswith("簡易裁判所") else "general")
            out.append(rec(court_id="jp-" + slug(name), name=name, level=tier, court_system=fam, country_code="JP", jurisdiction="JP", parent_court_id=None,
                address={"street": addr, "city": muni, "postcode": td[1], "region": m.group(1) if m else None, "country": "JP"}, geo={"lat": None, "lon": None},
                phone=ph.group(0) if ph else None, place_ids=[pid] if pid else [], place_match_method="wikidata_ja_label" if pid else None,
                court_family=fam, tier=tier, co_located_courts=name.split(), source_url=url, source_kind="official", site_policy="robots_allowed",
                license="courts.go.jp terms (public information)"))
        print(u, len(out), flush=True)
    return out
def es():
    import json, re
    ine = {}
    for r in csv.DictReader(open("/tmp/esine.csv")): ine.setdefault(r["c"].zfill(5), "wd:" + r["m"].rsplit("/", 1)[1])
    src = "https://analisi.transparenciacatalunya.cat/resource/uue8-bz7s.json"
    d = json.loads(get(src + "?$limit=20000&flg_estat=Alta", delay=2.0)); out = []
    for x in d:
        n = x["nom"]
        if n.startswith("Tribunal de Instancia de"): tier = "general"
        elif n.startswith("Audiencia Provincial de") or n.startswith("Tribunal Superior de Justicia"): tier = "appellate"
        else: continue
        c = (x.get("codi_municipi_seu") or "")[:5]; pid = ine.get(c)
        out.append(rec(court_id="es-" + slug(n), name=n, level=tier, court_system="ordinary", country_code="ES", jurisdiction="ES", parent_court_id="es-ordinary-" + tier,
            address={"street": None, "city": None, "postcode": None, "region": None, "country": "ES"}, geo={"lat": None, "lon": None}, ine_municipio=c or None,
            place_ids=[pid] if pid else [], place_match_method="wikidata_P772_ine" if pid else None, court_family="ordinary", tier=tier, organ_code=x["codi"],
            source_url="https://analisi.transparenciacatalunya.cat/d/uue8-bz7s", source_kind="official", site_policy="open_data_portal",
            license="Generalitat de Catalunya open data (CC BY 4.0)", valid_from=x.get("data_inici")))
    return out
B = {"PL": pl, "JP": jp, "ES": es}
if __name__ == "__main__":
    for cc in sys.argv[1:]: merge_into(cc.lower(), B[cc]())
