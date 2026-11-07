"""Shared helpers for rest-of-world courthouse builders: GeoNames cities500 nearest-city lookup, per-country place-name normalisation against global_municipalities (wd: ids)."""
import sys, csv, math, functools, collections
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from courts_common import *
GN = f"{ROOT}/data/ref/geonames"
STRIP = {
 "NZ": r"\b(city council|district council|regional council|council|district|city|region|unitary authority|territorial authority)$",
 "ZA": r"\b(local municipality|metropolitan municipality|district municipality|municipality|metropolitan)$",
 "MX": r"\b(municipality|municipio)$",
 "BR": r"^$",
 "KR": r"\b(special self-governing province|special self-governing city|metropolitan city|special city|province|district|city|county|gun|gu|si|do)$", "TW": r"\b(special municipality|county|city|township|district|rural township|urban township)$",
 "PH": r"\b(city|municipality|province|region)$", "AR": r"\b(partido|department|departamento|province|provincia|comuna)$", "CO": r"\b(department|departamento|municipio|distrito capital|distrito)$", "CL": r"\b(region|comuna|regi[oó]n|province)$",
 "NG": r"\b(local government area|local government|lga|state|area council|council)$", "KE": r"\b(county|city|municipality|sub-county)$",
 "JP": r"\b(shi|ku|machi|cho|mura|gun|city|ward|prefecture|ken|to|fu|do)$",
 "IN": r"\b(municipal corporation area|municipal corporation|municipality|municipal council|nagar panchayat|nagar palika|zilla panchayat|district panchayat|gram panchayat|block panchayat|janpad panchayat|jila panchayat|block|district|city|corporation|area|cantonment board|cantonment)$",
}
PREF = {"KR": r"^$", "PH": r"^(city of|municipality of|province of)\s+", "AR": r"^(partido de|departamento|departamento de|ciudad de|comuna)\s+", "CO": r"^(municipio de|departamento de)\s+", "CL": r"^(comuna de|regi[oó]n de|regi[oó]n del|regi[oó]n metropolitana de)\s+", "NG": r"^$", "KE": r"^$", "TW": r"^$", "MX": r"^(municipio de|heroica ciudad de|heroica|ciudad de|villa de)\s+", "BR": r"^(municipio de)\s+", "ZA": r"^(city of|city)\s+", "NZ": r"^(city of)\s+", "IN": r"^(city of)\s+"}
UNI_STRIP = {"TW": r"(市|縣|县|區|区|鄉|鄉鎮|鎮|镇|乡)$", "CN": r"(市|县|區|区|自治州|盟|地区|地區|省)$", "KR": r"(특별시|광역시|특별자치시|특별자치도|시|군|구|도)$", "RU": r"^(городской округ|муниципальный район|муниципальный округ|город|г\.)\s+|\s+(городской округ|муниципальный район|район|область|край)$",
             "SA": r"^(محافظة|مدينة|مركز|منطقة)\s+", "EG": r"^(محافظة|مدينة|مركز|قسم|حي)\s+", "AE": r"^(إمارة|مدينة)\s+", "TH": r"^(จังหวัด|อำเภอ|เทศบาลนคร|เทศบาลเมือง|เทศบาลตำบล|เขต)", "IL": r"^(עיריית|מועצה אזורית|מועצה מקומית)\s+", "MA": r"^(إقليم|عمالة|مدينة)\s+", "DZ": r"^(ولاية|دائرة|بلدية)\s+"}
_GENL = r"\b(governorate|province|region|district|municipality|state|metropolitan city|sub-metropolitan city|rural municipality|city)$"
for _c in ("JO", "LB", "TN", "IQ", "TZ", "LK", "NP", "MM", "UG", "SN", "CI", "CM"): STRIP[_c] = _GENL
_NEWCC = "KH BO PY UY CR PA GT DO ZM ZW UZ RS CH MG BY XK ML MD HK TJ AF RW BN GN BF NO YE MN HN SL MR NE SD AO AZ KG CU LA NI LR CD HT TD FM SO CF TG CG LY BJ AL SS GE AM MK IS SZ BA PS GA MZ SV BI GM SX BS KM MW SY CK MV FO SC TO ME GQ CV BT PG PW KN NA AI JM NR TL TT BM SR JE BB GY WS LI OM KP BW LS DM SM GG MU SB QA AG LC TC TV DJ AW BZ GD TM AD KW ER CW VC VU IM FJ EH GL GW MS BH KY VG KI MH VI VA ST NU MC IO SH".split()
for _c in _NEWCC: STRIP.setdefault(_c, _GENL)
_AR = r"^(محافظة|بلدية|لواء|قضاء|مدينة|ولاية|قضاء|ناحية)\s+"
for _c in ("JO", "LB", "TN", "IQ"): UNI_STRIP[_c] = _AR
def _unorm(s):
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = re.sub(r"[^\w ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()
def rcore(name, cc):
    n = norm(name)
    if not n:  # non-Latin script: ASCII norm is empty and would collide for every name
        n = _unorm(name)
        if cc in UNI_STRIP and n: n = re.sub(UNI_STRIP[cc], "", n).strip()
        return n
    for _ in range(2):
        if STRIP.get(cc): n = re.sub(STRIP[cc], "", n).strip()
        if PREF.get(cc): n = re.sub(PREF[cc], "", n).strip()
    return n
@functools.lru_cache(None)
def pidx(cc):
    idx = {}; q2p = {}
    with open(GM, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["country_code"] != cc or not r.get("place_id"): continue
            k_ = rcore(r["place_name"], cc)
            if not k_: continue
            idx.setdefault(k_, []).append((_rank(r["admin_level"]), r["place_id"], r["place_name"], r["admin_level"], r.get("population") or ""))
            if r.get("qid"): q2p[r["qid"]] = r["place_id"]
    return idx, q2p
def _rank(l): return {"municipality": 0, "district": 2, "block": 3, "gram_panchayat": 5, "state": 6, "territory": 6, "province": 6, "prefecture": 6, "region": 6}.get(l, 7)
def rmatch(names, cc, states_ok=False):
    idx, _ = pidx(cc); out = []
    for nm in names:
        if not nm: continue
        c = rcore(nm, cc); cands = idx.get(c) if c else None
        if cands:
            cands = [x for x in cands if states_ok or x[0] < 6] or cands
            cands = sorted(cands, key=lambda x: (x[0], pop(x)))
            if cands[0][1] not in out: out.append(cands[0][1])
    return out
def qplace(q, cc):
    return pidx(cc)[1].get(q)
def state_place(name, cc):
    idx, _ = pidx(cc)
    for x in sorted(idx.get(rcore(name, cc), []), key=lambda x: x[0]):
        if x[0] >= 6: return x[1]
@functools.lru_cache(None)
def gn_cities(cc):
    out = []
    for l in open(f"{GN}/cities500.txt", encoding="utf-8"):
        p = l.split("\t")
        if p[8] == cc: out.append((float(p[4]), float(p[5]), p[1], p[10], int(p[14] or 0), p[0], p[11]))
    return out
@functools.lru_cache(None)
def gn_admin2(cc):
    d = {}
    for l in open(f"{GN}/admin2Codes.txt", encoding="utf-8"):
        p = l.rstrip("\n").split("\t")
        if p[0].startswith(cc + "."): d[p[0][3:]] = p[1]
    return d
@functools.lru_cache(None)
def gn_admin1(cc):
    d = {}
    for l in open(f"{GN}/admin1CodesASCII.txt", encoding="utf-8"):
        p = l.rstrip("\n").split("\t")
        if p[0].startswith(cc + "."): d[p[0][3:]] = (p[1], p[2])
    return d
_grid = {}
def nearest_city(lat, lon, cc, maxkm=25):
    g = _grid.get(cc)
    if g is None:
        g = collections.defaultdict(list)
        for c in gn_cities(cc): g[(int(c[0]), int(c[1]))].append(c)
        _grid[cc] = g
    best = None
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            for c in g.get((int(lat) + dy, int(lon) + dx), ()):
                d = haversine((lat, lon), (c[0], c[1]))
                if d <= maxkm * 1000 and (best is None or d < best[0]): best = (d, c)
    return best[1] if best else None
def load_jl(p): return rjl(p)
