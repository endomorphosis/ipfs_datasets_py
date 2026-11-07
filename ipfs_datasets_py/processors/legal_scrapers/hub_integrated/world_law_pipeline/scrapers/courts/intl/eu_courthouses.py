"""Build data/<cc>/<cc>_courthouses.jsonl for the 27 EU Member States + EU level (CJEU).
Sources: e-Justice European Court Database (CDB) open API (data/ref/cdb), OSM amenity=courthouse (ODbL), Wikidata courthouses (CC0),
GeoNames (CC-BY 4.0: cities500 + postal-code centroids, GeoNames ids from CDB -> coordinates), upstream endomorphosis/ipfs_{ireland,netherlands,germany}_courts (imported, deduped, provenance in `upstream`).
Place ids: Wikidata P1566 (GeoNames id) -> wd: ids present in global_municipalities, else normalised-name match."""
import sys, json, csv, os, re, glob, collections, math, unicodedata
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from courts_common import *
from rapidfuzz import fuzz
import pandas as pd
EUD = f"{ROOT}/data/eu"; GN = f"{ROOT}/data/ref/geonames"
EU = "AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE".split()
CN = dict(AT="Austria", BE="Belgium", BG="Bulgaria", HR="Croatia", CY="Cyprus", CZ="Czechia", DK="Denmark", EE="Estonia", FI="Finland", FR="France", DE="Germany", GR="Greece", HU="Hungary", IE="Ireland", IT="Italy", LV="Latvia", LT="Lithuania", LU="Luxembourg", MT="Malta", NL="Netherlands", PL="Poland", PT="Portugal", RO="Romania", SK="Slovakia", SI="Slovenia", ES="Spain", SE="Sweden")
# ---------------- classification (name keyword, accent-folded, multilingual) -> (family, tier)
from unidecode import unidecode
def f(s): return unidecode(unicodedata.normalize("NFC", s or "")).lower().replace("’", "'")
CLS = [  # order matters
 ("constitutional", "supreme", r"verfassungsgericht|verfassungsgerichtshof|corte costituzionale|tribunal constitucional|trybunal konstytucyjny|conseil constitutionnel|cour constitutionnelle|grondwettelijk hof|ustavni sud|ustavno sodisce|ustavni soud|constitutional court|alkotmanybirosag|curtea constitutionala|ustavny sud|riigikohus|perustuslaki|ανώτατο συνταγματικό|anotato syntagmatiko|tribunal constitutional"),
 ("administrative", "supreme", r"sumboulio tes epikrateias|symboulio tes epikrateias|bundesverwaltungsgericht|conseil d'etat|consiglio di stato|raad van state|naczelny sad administracyjny|nejvyssi spravni|najvyssi spravny|varhoven administrativen|vrhovni upravni|visoki upravni|symvoulio|συμβούλιο της επικρατείας|verwaltungsgerichtshof|korkein hallinto|hogsta forvaltningsdomstolen|curtea suprema.*administrativ|supreme administrative|tribunal supremo.*contencioso|riigikohus.*halduskolleegium|augstaka tiesa.*administrativ|lietuvos vyriausiasis administracinis"),
 ("labour", "supreme", r"bundesarbeitsgericht"), ("social", "supreme", r"bundessozialgericht"), ("fiscal", "supreme", r"bundesfinanzhof"),
 ("ordinary", "supreme", r"areios pag|anotato dikastirio|varhoven|oberster gerichtshof|bundesgerichtshof|cour de cassation|hof van cassatie|hoge raad|tribunal supremo|corte suprema di cassazione|corte di cassazione|sad najwyzszy|varhoven kasatsionen|vrhovni sud|vrhovno sodisce|hojesteret|hogsta domstolen|korkein oikeus|riigikohus|augstaka tiesa|aukscia?usiasis teismas|najvyssi sud|nejvyssi soud|kuria|areios pagos|άρειος πάγος|areios|ανώτατο δικαστήριο|anotato dikastirio|inalta curte|supremo tribunal de justica|supreme court|court of cassation|cour supreme|curtea suprema|tribunal supremo|ανώτατο|ανωτατο|najvyssi|nejvyssi|korkein|hogsta|högsta|hoyesterett"),
 ("administrative", "appellate", r"oberverwaltungsgericht|verwaltungsgerichtshof|cour administrative d'appel|cour administrative|tribunal central administrativo|wojewodzki sad administracyjny|centrale raad|college van beroep|administrativen sad.*apelativ|visoki upravni|hovioikeus.*hallinto|kammarratt|kammarrätt|tribunal superior.*contencioso|sala de lo contencioso|vrchni soud.*sprav|administratyvinis apygardos|apgabaltiesa.*administrativ|curtea de apel.*contencios"),
 ("labour", "appellate", r"landesarbeitsgericht|cour du travail|arbeidshof|tribunal superior.*social|sala de lo social|sad apelacyjny.*pracy|tribunal da relacao.*trabalho|curtea de apel.*munc"),
 ("social", "appellate", r"landessozialgericht"), ("fiscal", "appellate", r"finanzgericht(?!.*hof)"),
 ("administrative", "general", r"dioikitik|diikitik|verwaltungsgericht|tribunal administratif|tribunal administrativo|tribunale amministrativo regionale|^tar |wojewodzki sad|upravni sud|upravni soud|administrativen sad|spravni|upravno sodisce|administrativ.*court|forvaltningsratt|förvaltningsrätt|hallinto-oikeus|halduskohus|administratyvinis|administrativ|juzgado.*contencioso|tribunal.*contencios|contentieux administratif|conseil du contentieux|raad voor vreemdelingen|διοικητικ|diikitik"),
 ("labour", "general", r"arbeitsgericht|arbeits- und sozialgericht|conseil de prud|tribunal du travail|arbeidsrechtbank|juzgado de lo social|tribunale.*lavoro|sezione lavoro|sad pracy|tribunal do trabalho|arbetsdomstolen|tyontuomioistuin|työtuomioistuin|labour court|employment tribunal|tribunal de trabajo|tribunalul.*munc|pracovni|työ|employment|ειδικό.*εργατικ|εργατικ"),
 ("social", "general", r"sozialgericht|tribunal des affaires de securite sociale|tass|pole social|social|sociale"),
 ("fiscal", "general", r"finanzgericht|tribunal fiscal|tax tribunal|skatteret|veroikeus|tribunal tributario|commissione tributaria|corte di giustizia tributaria|wojewodzki sad.*podat"),
 ("commercial", "general", r"handelsgericht|tribunal de commerce|tribunal de l'entreprise|ondernemingsrechtbank|rechtbank van koophandel|juzgado de lo mercantil|tribunale delle imprese|sad gospodarczy|tribunal de comercio|tribunal da concorrencia|commercial court|handelsrechtbank"),
 ("ordinary", "appellate", r"efeteio|efetio|apelativ|oberlandesgericht|kammergericht|cour d'appel|cour d appel|hof van beroep|gerechtshof|tribunal superior de justicia|audiencia nacional|corte d'appello|corte di appello|sad apelacyjny|apelativen|apelacinis|apgabaltiesa|ringkonnakohus|hovratt|hovrätt|hovioikeus|landsret|vestre landsret|ostre landsret|østre landsret|vrchni soud|odvolaci|krajsky sud.*odvol|court of appeal|curtea de apel|tribunal da relacao|visoki trgovacki|visoki prekrsajni|visoki kazneni|visoki sud|visoko sodisce|visoko|εφετείο|efeteio|ανώτερο δικαστήριο|appeal|beroep|apelaci|fellebbviteli|tabla|itelotabla|ítélőtábla|oberlandes"),
 ("ordinary", "general", r"protodik|okr.zhen|okruzhen|court of first instance|multi-member|landgericht|landesgericht|tribunal judiciaire|tribunal de grande instance|tribunal de premiere instance|rechtbank van eerste aanleg|rechtbank|audiencia provincial|tribunale|sad okregowy|okrazhen sad|okruzhen|zupanijski sud|okrozno sodisce|okresni soud.*krajsk|krajsky sud|krajsk|county court|circuit court|high court|regional court|apygardos|apgabal|maakohus|ringkonna|tingsratt|tingsrätt|district court.*sweden|byret|retten i|karajoikeus|käräjäoikeus|tribunal de comarca|curtea|tribunalul|tribunal|megyei|torvenyszek|törvényszék|πρωτοδικείο|protodikeio|court of first instance|cour de premiere instance|rechtbank"),
 ("ordinary", "limited", r"eir[ei]nodik|raionen|rayonen|magistrates|single-member|amtsgericht|bezirksgericht|tribunal de proximite|tribunal d'instance|tribunal de police|juzgado|giudice di pace|kantongerecht|vredegerecht|justice de paix|sad rejonowy|rajonen sad|opcinski sud|općinski|okrajno sodisce|okresni soud|okresny sud|district court|justice of the peace|ειρηνοδικείο|eirinodikeio|rajonu tiesa|apylinkes teismas|apylinkės|kohtuinfo|jugado|tribunal de paz|judecatoria|jarasbirosag|járásbíróság|sad grodzki|rajon|letseie|local court|tribunal de pequena|tribunal judicial de comarca|tribunal de comarca|ostreg|uzemni|prekrsajni|prekršajni|trgovacki sud|trgovački"),
]
CLSC = [(a, b, re.compile(c)) for a, b, c in CLS]
EXCL = re.compile(r"ministeri|ministry|ministere|ministère|ministero|ministerstvo|ministarstvo|ministerie|ministerio|minister|bundesministerium|central authority|zentralbehorde|autorite centrale|autoridad central|autorita centrale|centrale autoriteit|authority|directorate|department|notar|huissier|bailiff|gerechtsdeurwaarder|deurwaarder|exekutor|gerichtsvollzieher|staatsanwalt|parquet|procura|prokuratur|prokuratuur|prokuratura|ufficio|oficina|service public|office of|bureau|agency|centralised office|test authority|do not use|for all matters|for matters|regulation|competent for|kancelaria|social insurance|ombuds|bar association|chamber of|kamer van|ordre des|rechtsanwalt|advokat|mediator|coordinat|international legal|cooperation|unit\b|referat|servicio|unidad|ministre|ministr|justice minister|inspect|registre|register of|pension|colegio de|abogados|ilustre|testing|prueba|izba|komorn|ambulante soziale|bewahrungshilfe|raad voor|conseil national|chambre nationale|chambre des|antenne de justice|maison de justice|point.?justice|entraide|bar council|law society|advocaten|barreau|ordem dos|procurador|orde van|kamer van|prison|justizvollzug|bewaehrungshilfe|gerichtshilfe|sozialer dienst|opferhilfe", re.I)
LEVEL = {("ordinary", "supreme"): "supreme", ("constitutional", "supreme"): "supreme", ("ordinary", "appellate"): "appellate", ("ordinary", "general"): "trial_general", ("ordinary", "limited"): "trial_limited", ("commercial", "general"): "specialized"}
def classify(name, ctypes):
    n = f(name)
    for fam, tier, rx in CLSC:
        if rx.search(n): return fam, tier, "name_keyword"
    for t in ctypes or []:
        if t == "2": return "ordinary", "supreme", "cdb_court_type"
        if t == "1": return "ordinary", "appellate", "cdb_court_type"
        if t == "0": return "ordinary", "limited", "cdb_court_type"
    return "other", None, "unclassified"
def level_of(fam, tier):
    if tier is None: return "other"
    if tier == "supreme": return "supreme"
    if tier == "appellate": return "appellate"
    if (fam, tier) in LEVEL: return LEVEL[(fam, tier)]
    return "administrative" if fam == "administrative" else "specialized"
# ---------------- reference data
def load_geonames():
    ci = {}; nm = collections.defaultdict(list)
    for l in open(f"{GN}/cities500.txt", encoding="utf-8"):
        p = l.rstrip("\n").split("\t")
        if p[8] not in EU + ["GR"]: continue
        ci[p[0]] = (float(p[4]), float(p[5]), p[1], p[8], int(p[14] or 0))
        for n in {p[1], p[2], *p[3].split(",")[:0]}: nm[(p[8], norm(n))].append(p[0])
    post = collections.defaultdict(dict)
    for cc in EU:
        fn = f"{GN}/{cc}.txt"
        if not os.path.exists(fn): continue
        for l in open(fn, encoding="utf-8"):
            p = l.rstrip("\n").split("\t")
            try: post[cc].setdefault(re.sub(r"\s", "", p[1]).upper(), (float(p[9]), float(p[10]), p[3], p[2]))
            except Exception: pass
    return ci, nm, post
def load_places():
    P = {cc: {} for cc in EU}; N = {cc: collections.defaultdict(list) for cc in EU}
    for r in csv.DictReader(open(GM, newline="", encoding="utf-8")):
        cc = r["country_code"]
        if cc in P and r.get("place_id"):
            try: pp = float(r.get("population") or 0)
            except Exception: pp = 0
            P[cc][r["place_id"]] = (r["place_name"], r["admin_level"], pp); N[cc][norm(r["place_name"])].append((0 if r["admin_level"] == "municipality" else 1, -pp, r["place_id"], r["admin_level"]))
    return P, N
CI, NM, POST = load_geonames(); PL, PLN = load_places()
def gn2q(cc):
    fn = f"{EUD}/gn_{cc}.tsv"; d = {}
    if os.path.exists(fn):
        for l in open(fn):
            a = l.rstrip("\n").split("\t")
            if len(a) == 2: d[a[1]] = a[0]
    return d
P131 = {}
for _fn in glob.glob(f"{EUD}/p131_*.json"): P131.update(json.load(open(_fn)))
NEED = collections.defaultdict(set)
def place_for(cc, gids, gmap, city):
    ids = []; method = None
    for g in gids or []:
        q = gmap.get(g)
        if q and f"wd:{q}" in PL[cc]:
            ids.append(f"wd:{q}"); method = "geonames_p1566"; break
    if not ids:
        for g in gids or []:
            q = gmap.get(g)
            if not q: continue
            if q in P131:
                for a in P131[q]:
                    if f"wd:{a}" in PL[cc]: ids.append(f"wd:{a}"); method = "geonames_p1566+p131"; break
                if ids: break
            else: NEED[cc].add(q)
    if not ids and city:
        c = PLN[cc].get(norm(city)) or PLN[cc].get(norm(re.sub(r"\(.*?\)|\s+\d+.*$", "", city)))
        if c:
            c = sorted(c)[0]; ids = [c[2]]; method = "name"
    return ids, method
def pick_geoname(gids, pc, cc):
    cands = [g for g in gids or [] if g in CI and CI[g][3] == cc]
    if not cands: return None
    pcc = POST[cc].get(re.sub(r"\s", "", pc or "").upper()) if pc else None
    if pcc and len(cands) > 1: cands.sort(key=lambda g: haversine((CI[g][0], CI[g][1]), (pcc[0], pcc[1])))
    elif len(cands) > 1: cands.sort(key=lambda g: -CI[g][4])
    return cands[0]
# ---------------- pools
def pool(cc):
    rows = []
    for fn in (f"{EUD}/osm_{cc}.jsonl", f"{EUD}/wd_{cc}.jsonl"):
        if os.path.exists(fn):
            for l in open(fn):
                r = json.loads(l); r["src"] = "osm" if "osm_id" in r else "wd"; rows.append(r)
    byq = {}; out = []
    for r in sorted(rows, key=lambda r: r["src"] != "osm"):
        q = r.get("wikidata")
        if q and q in byq:
            t = byq[q]
            for k in ("street", "city", "postcode", "phone", "website", "lat", "lon"):
                if t.get(k) is None and r.get(k) is not None: t[k] = r[k]
            t["wd_src"] = True; continue
        if not r.get("name"): continue
        # near-duplicate (same name within 150 m)
        dup = None
        if r.get("lat") is not None:
            for t in out:
                if t.get("lat") is not None and abs(t["lat"] - r["lat"]) < 0.002 and abs(t["lon"] - r["lon"]) < 0.003 and norm(t["name"]) == norm(r["name"]): dup = t; break
        if dup:
            if r.get("wikidata") and not dup.get("wikidata"): dup["wikidata"] = r["wikidata"]
            continue
        out.append(r)
        if q: byq[q] = r
    return out
def cdb_rows(cc):
    cd = "EL" if cc == "GR" else cc; fn = f"{ROOT}/data/ref/cdb/{cd}.json"; out = []; excl = 0
    if not os.path.exists(fn): return out, 0
    for b in json.load(open(fn)):
        if b.get("bodyType") != "COURT": excl += 1; continue
        ds = b["details"]; d0 = next((d for d in ds if d.get("lang") == "en"), ds[0]); dl = next((d for d in ds if d.get("lang") != "en"), ds[0])
        nm_ = (dl.get("name") or d0.get("name") or "").strip()
        if not nm_ or EXCL.search(f(nm_)) or EXCL.search(f(d0.get("name") or "")): excl += 1; continue
        out.append({"cdb_id": b["id"], "name": d0.get("name").strip() if d0.get("name") else nm_, "name_local": nm_, "d": dl, "ctypes": b.get("courtTypes") or [], "ecli": b.get("ecliCode")})
    return out, excl
NOISE = re.compile(r"notar|justizanstalt|prison|gefangnis|strafanstalt|penitenc|polizei|police|jail|carcel|prigione|haftanstalt|vollzug|bailiff|huissier|gerichtsvollzieher|ufficiale giudiziario|detention|arrest")
COURTISH = re.compile(r"gericht|court|tribunal|justice|justiz|palais|palace|palazzo|giustizia|giudic|juzgado|audiencia|justicia|cour\b|rechtbank|rechtspraak|gerecht|sad\b|sud\b|soud|sod|kohus|teismas|tiesa|domstol|oikeus|dikast|δικαστ|ανακριτ|birosag|bir[oó]s[aá]g|curte|judecat|palatul|tribunale|justitie|justi|tingsratt|tingsrätt|hovr|landsret|byret|rett|kuria|areios|vyriausiasis|apygard|apylink|apgabal|rajona")
def toks(n): return [t for t in norm(n).split() if len(t) > 2]
def build_cc(cc, upstream=None):
    cdb, excl = cdb_rows(cc); P = pool(cc); gmap = gn2q(cc); rows = []; used = set(); stats = collections.Counter(); stats["cdb_excluded"] = excl
    for c in cdb:
        d = c["d"]; fam, tier, basis = classify(c["name_local"] + " " + c["name"], c["ctypes"]); gid = pick_geoname(d.get("courtGeoNameIds"), d.get("postalCode"), cc)
        cen = (CI[gid][0], CI[gid][1]) if gid else None; geo = None; gsrc = None; wd = None
        pc = POST[cc].get(re.sub(r"\s", "", d.get("postalCode") or "").upper()) if d.get("postalCode") else None
        if cen is None and pc: cen = (pc[0], pc[1]); gsrc = "geonames_postcode"
        if cen is None and d.get("municipality"):
            gl = NM.get((cc, norm(d["municipality"]))) or NM.get((cc, norm(re.sub(r"\(.*?\)|\s+\d+.*$", "", d["municipality"]))))
            if gl:
                g_ = max(gl, key=lambda g: CI[g][4]); cen = (CI[g_][0], CI[g_][1]); gsrc = "geonames_municipality_name"
        best = None
        if cen:
            for i, p in enumerate(P):
                if p.get("lat") is None or abs(p["lat"] - cen[0]) > 0.15 or abs(p["lon"] - cen[1]) > 0.25: continue
                fam2, tier2, b2 = classify(p["name"], [])
                if b2 == "name_keyword" and basis == "name_keyword" and (fam2, tier2) != (fam, tier): continue
                sc = fuzz.token_sort_ratio(f(c["name_local"]), f(p["name"]))
                if p.get("postcode") and d.get("postalCode") and re.sub(r"\s", "", p["postcode"]).upper() == re.sub(r"\s", "", d["postalCode"]).upper(): sc += 8
                if sc >= 78 and (best is None or sc > best[0]): best = (sc, i)
        if best:
            p = P[best[1]]; geo = {"lat": p["lat"], "lon": p["lon"]}; gsrc = "osm" if p["src"] == "osm" else "wikidata"; wd = p.get("wikidata"); used.add(best[1])
        elif cen:
            geo = {"lat": cen[0], "lon": cen[1]}; gsrc = gsrc or "geonames_municipality"
        city = d.get("municipality") or (CI[gid][2] if gid else None)
        ids, meth = place_for(cc, d.get("courtGeoNameIds"), gmap, city)
        rows.append(rec(court_id=None, name=c["name"], name_local=c["name_local"] if c["name_local"] != c["name"] else None, level=level_of(fam, tier), court_system=fam, country_code=cc, jurisdiction=cc,
              address={"street": d.get("address"), "city": city, "postcode": d.get("postalCode"), "region": (pc[2] if pc else None), "country": cc}, geo=geo or {"lat": None, "lon": None}, phone=d.get("tel"), website=d.get("web"),
              wikidata=wd, place_ids=ids, source_url=f"https://e-justice.europa.eu/content_find_a_court-1.do?cdb={c['cdb_id']}&country={cc}" if False else "https://webgate.ec.europa.eu/cdb/search", source_kind="official",
              site_policy="open_api_documented", license="EU e-Justice Court Database open data (reuse: Commission Decision 2011/833/EU, CC-BY 4.0)", sources=[{"source_url": "https://webgate.ec.europa.eu/cdb/search", "site_policy": "open_api_documented", "source_kind": "official", "cdb_id": c["cdb_id"]}] + ([{"source_url": "https://www.openstreetmap.org/" + P[best[1]]["osm_id"], "site_policy": "open_license:ODbL", "source_kind": "osm"}] if best and P[best[1]]["src"] == "osm" else []),
              place_match_method=meth, geo_source=gsrc, email=d.get("email"), court_family=fam, tier=tier, level_basis=basis, cdb_id=c["cdb_id"], ecli_code=c.get("ecli"), geoname_ids=[str(x) for x in (d.get("courtGeoNameIds") or [])][:6],
              accepted_languages=d.get("acceptedLanguages"), upstream=None)); stats["cdb"] += 1
    # OSM / Wikidata courts not matched to a CDB row
    for i, p in enumerate(P):
        if i in used: continue
        fam, tier, basis = classify(p["name"], [])
        if NOISE.search(f(p["name"])) or (basis == "unclassified" and not COURTISH.search(f(p["name"]))): stats["pool_dropped_noncourt"] += 1; continue
        city = p.get("city"); ids, meth = place_for(cc, [], {}, city)
        if not ids and p.get("lat") is not None:
            # nearest geonames city within 6 km -> name match
            bestg = None
            for g, v in CI.items():
                if v[3] != cc or abs(v[0] - p["lat"]) > 0.06 or abs(v[1] - p["lon"]) > 0.09: continue
                dd = haversine((v[0], v[1]), (p["lat"], p["lon"]))
                if dd < 6000 and (bestg is None or dd < bestg[0]): bestg = (dd, g)
            if bestg:
                ids, meth = place_for(cc, [bestg[1]], gmap, CI[bestg[1]][2]); city = city or CI[bestg[1]][2]
        src_osm = p["src"] == "osm"
        rows.append(rec(court_id=None, name=p["name"], level=level_of(fam, tier), court_system=fam, country_code=cc, jurisdiction=cc,
              address={"street": p.get("street"), "city": city, "postcode": p.get("postcode"), "region": None, "country": cc}, geo={"lat": p.get("lat"), "lon": p.get("lon")}, phone=p.get("phone"), website=p.get("website"),
              wikidata=p.get("wikidata"), place_ids=ids, place_match_method=meth, source_url=("https://www.openstreetmap.org/" + p["osm_id"]) if src_osm else f"https://www.wikidata.org/wiki/{p['wikidata']}",
              source_kind="osm" if src_osm else "wikidata", site_policy="open_license:ODbL" if src_osm else "open_license:CC0", license="ODbL-1.0 (c) OpenStreetMap contributors" if src_osm else "CC0-1.0", geo_source="osm" if src_osm else "wikidata",
              court_family=fam, tier=tier, level_basis=basis)); stats["pool_only"] += 1
    return rows, stats
def dedupe_pool(rows, stats):
    anchors = [r for r in rows if r["record_type"] == "courthouse" and (r.get("cdb_id") or r.get("upstream")) and (r["geo"] or {}).get("lat") is not None]
    keep = []; dropped = 0
    for r in rows:
        if r["record_type"] == "courthouse" and not r.get("cdb_id") and not r.get("upstream") and r["source_kind"] in ("osm", "wikidata") and (r["geo"] or {}).get("lat") is not None:
            hit = None
            for a in anchors:
                if abs(a["geo"]["lat"] - r["geo"]["lat"]) > 0.003 or abs(a["geo"]["lon"] - r["geo"]["lon"]) > 0.005: continue
                if fuzz.token_sort_ratio(f(a["name"]), f(r["name"])) >= 70 or (a.get("court_family") == r.get("court_family") and a.get("tier") == r.get("tier") and a.get("tier")): hit = a; break
            if hit:
                if r.get("wikidata") and not hit.get("wikidata"): hit["wikidata"] = r["wikidata"]
                hit["sources"].append(r["sources"][0]); dropped += 1; continue
        keep.append(r)
    stats["pool_deduped_vs_anchor"] = dropped
    return keep
def finish(cc, rows):
    """ids, hierarchy bodies, parent links"""
    seen = collections.Counter(); out = []
    for r in rows:
        if r["court_id"] is None:
            base = f"{cc.lower()}-{slug(r['name'] or r.get('name_local') or 'court')}"[:90]; seen[base] += 1
            r["court_id"] = base if seen[base] == 1 else f"{base}~{seen[base]}"
        out.append(r)
    ORDER = ["limited", "general", "appellate", "supreme"]; fams = collections.defaultdict(set)
    for r in out:
        if r.get("tier"): fams[r["court_family"]].add(r["tier"])
    bodies = []
    for fam, tiers in fams.items():
        ts = [t for t in ORDER if t in tiers]
        for i, t in enumerate(ts):
            bodies.append(rec(court_id=f"{cc.lower()}-{fam}-{t}", record_type="court_body", name=f"{CN[cc]} - {fam} courts - {t} tier", level=level_of(fam, t), court_system=fam, country_code=cc, jurisdiction=cc,
                parent_court_id=(f"{cc.lower()}-{fam}-{ts[i+1]}" if i + 1 < len(ts) else None), address=None, geo=None, source_url="https://webgate.ec.europa.eu/cdb/search", source_kind="official", site_policy="derived", court_family=fam, tier=t,
                level_basis="derived_hierarchy", license="derived from CDB/OSM/Wikidata rows; CC-BY-4.0 / ODbL / CC0"))
    for r in out:
        if r.get("tier"): r["parent_court_id"] = f"{cc.lower()}-{r['court_family']}-{r['tier']}"
    return bodies + out
UPS = {"IE": ("ipfs_ireland_courts", "courts-ie-psi-reuse"), "NL": ("ipfs_netherlands_courts", "rechtspraak-open-data-reuse"), "DE": ("ipfs_germany_courts", "xrepository-codelist-public")}
def merge_upstream(cc, rows):
    """import endomorphosis upstream courts; merge into matching CDB/OSM row (keep upstream court_id), else add."""
    ds, lic = UPS[cc]; u = pd.read_parquet(f"{ROOT}/data/ref/hf_intl_{cc.lower()}/data/courts-00000.parquet"); added = merged = 0
    cand = [r for r in rows if r["record_type"] == "courthouse"]; idx = collections.defaultdict(list)
    for r in cand: idx[norm(r["name"])].append(r); r.get("name_local") and idx[norm(r["name_local"])].append(r)
    keys = list(idx)
    for _, x in u.iterrows():
        nmx = x["name"] or ""; hit = None
        if norm(nmx) in idx: hit = idx[norm(nmx)][0]
        else:
            m = [(fuzz.token_sort_ratio(norm(nmx), k), k) for k in keys]
            m = [a for a in m if a[0] >= 93]
            if m: hit = idx[max(m)[1]][0]
        up = {"dataset": f"endomorphosis/{ds}", "court_id": x["court_id"], "license": lic, "source_url": x["source_url"]}
        if hit is not None and not hit.get("upstream") and not str(hit["court_id"]).startswith(x["court_id"][:2] + "-") is None:
            pass
        if hit is not None and not hit.get("upstream"):
            hit["upstream"] = up; hit["upstream_court_id"] = x["court_id"]; hit["sources"].append({"source_url": x["source_url"], "site_policy": "upstream_dataset", "source_kind": "official", "dataset": f"endomorphosis/{ds}"})
            merged += 1; continue
        city = x.get("locality") if isinstance(x.get("locality"), str) else None
        lat = x["lat"] if pd.notna(x.get("lat")) else None; lon = x["lon"] if pd.notna(x.get("lon")) else None
        fam, tier, basis = classify(nmx, []); geo = {"lat": lat, "lon": lon}; gsrc = "upstream" if lat is not None else None
        if lat is None and cc in ("DE", "NL"):  # infer city from name tail, centroid of the municipality (low precision)
            m_ = re.sub(r"^(?:\S+gericht|Gerechtshof|Rechtbank|Landgericht|Amtsgericht|Oberlandesgericht|Registergericht|Familiengericht|Insolvenzgericht|Vollstreckungsgericht|Nachlassgericht|Betreuungsgericht|Grundbuchamt|Handelsregister|Zwangsvollstreckung\w*)\s+(?:Amtsgericht\s+)?", "", nmx).strip(); m_ = re.sub(r"\s*\(.*?\)|\s+-.*$|,.*$", "", m_)
            gl = NM.get((cc, norm(m_)))
            if gl:
                g = max(gl, key=lambda g: CI[g][4]); geo = {"lat": CI[g][0], "lon": CI[g][1]}; gsrc = "geonames_municipality_inferred"; city = city or CI[g][2]
        ids, meth = place_for(cc, [], {}, city)
        if not ids and city is None and cc in ("DE", "NL"):
            pass
        rows.append(rec(court_id=x["court_id"], name=nmx, level=x["level"] if x["level"] in ("trial_limited", "trial_general", "appellate", "supreme", "administrative", "specialized") else level_of(fam, tier), court_system=fam, country_code=cc, jurisdiction=cc,
            address={"street": x.get("address_street") if isinstance(x.get("address_street"), str) else None, "city": city, "postcode": x.get("postcode") if isinstance(x.get("postcode"), str) else None, "region": x.get("region") if isinstance(x.get("region"), str) else None, "country": cc},
            geo=geo, phone=None, website=None, place_ids=ids, place_match_method=meth, source_url=x["source_url"], source_kind="official", site_policy="upstream_dataset", license=lic, geo_source=gsrc, court_family=fam, tier=tier, level_basis="upstream_level",
            upstream=up, upstream_court_id=x["court_id"], ecli_code=x.get("ecli_code") if isinstance(x.get("ecli_code"), str) else None, parent_court_id=x["parent_court_id"] if isinstance(x.get("parent_court_id"), str) else None,
            sources=[{"source_url": x["source_url"], "site_policy": "upstream_dataset", "source_kind": "official", "dataset": f"endomorphosis/{ds}"}])); added += 1
    return merged, added
def eu_level():
    q = rec(court_id="eu-cjeu", record_type="court_body", name="Court of Justice of the European Union", name_local="Cour de justice de l'Union européenne", level="supreme", court_system="eu", country_code="EU", jurisdiction="EU", wikidata="Q4951", address=None, geo=None,
            source_url="https://curia.europa.eu/", source_kind="official", site_policy="robots_allowed", license="CC-BY-4.0 (EU reuse, Decision 2011/833/EU)", court_family="eu", tier="supreme", level_basis="manual")
    ad = {"street": "Rue du Fort Niedergruenewald", "city": "Luxembourg", "postcode": "L-2925", "region": "Luxembourg", "country": "LU"}
    ids, m = place_for("LU", [], {}, "Luxembourg")
    cj = rec(court_id="eu-cjeu-court-of-justice", name="Court of Justice", name_local="Cour de justice", level="supreme", court_system="eu", country_code="EU", jurisdiction="EU", parent_court_id="eu-cjeu", wikidata="Q1518827", address=ad, geo={"lat": 49.62, "lon": 6.13944}, phone="+352 4303-1", website="https://curia.europa.eu/",
             place_ids=ids, place_match_method=m, source_url="https://www.wikidata.org/wiki/Q4951", source_kind="wikidata", site_policy="open_license:CC0", license="CC0-1.0 (Wikidata coordinates); address from curia.europa.eu", geo_source="wikidata", court_family="eu", tier="supreme", level_basis="manual")
    gc = rec(court_id="eu-cjeu-general-court", name="General Court", name_local="Tribunal", level="appellate", court_system="eu", country_code="EU", jurisdiction="EU", parent_court_id="eu-cjeu-court-of-justice", wikidata="Q740574", address=ad, geo={"lat": 49.62, "lon": 6.13944}, phone="+352 4303-1", website="https://curia.europa.eu/",
             place_ids=ids, place_match_method=m, source_url="https://www.wikidata.org/wiki/Q740574", source_kind="wikidata", site_policy="open_license:CC0", license="CC0-1.0 (Wikidata coordinates); address from curia.europa.eu", geo_source="wikidata", court_family="eu", tier="appellate", level_basis="manual")
    return [q, cj, gc]
if __name__ == "__main__":
    allstats = {}
    for cc in (sys.argv[1:] or EU):
        rows, st = build_cc(cc)
        if cc in UPS:
            m, a = merge_upstream(cc, rows); st["upstream_merged"] = m; st["upstream_added"] = a
        rows = dedupe_pool(rows, st); rows = finish(cc, rows)
        os.makedirs(f"{ROOT}/data/{cc.lower()}", exist_ok=True); wjl(f"{ROOT}/data/{cc.lower()}/{cc.lower()}_courthouses.jsonl", rows)
        ch = [r for r in rows if r["record_type"] == "courthouse"]; st["courthouses"] = len(ch); st["bodies"] = len(rows) - len(ch)
        st["geo"] = sum(1 for r in ch if (r["geo"] or {}).get("lat") is not None); st["precise_geo"] = sum(1 for r in ch if r.get("geo_source") in ("osm", "wikidata", "upstream")); st["place_ids"] = sum(1 for r in ch if r["place_ids"])
        allstats[cc] = dict(st); print(cc, dict(st), flush=True)
        json.dump({k: sorted(v) for k, v in NEED.items()}, open(f"{EUD}/need_p131_{'_'.join(sys.argv[1:]) or 'all'}.json", "w"))
        json.dump(allstats, open(f"{EUD}/build_stats_{'_'.join(sys.argv[1:]) or 'all'}.json", "w"))
    if not sys.argv[1:] or "EU" in sys.argv[1:]:
        os.makedirs(f"{ROOT}/data/eu", exist_ok=True); wjl(f"{ROOT}/data/eu/eu_courthouses.jsonl", eu_level())
