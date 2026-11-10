"""Shared helpers for GB/CA/AU courthouse builders (world_courts phase 5)."""
import csv, json, re, time, unicodedata, urllib.request, urllib.parse, os, datetime, functools
ROOT = "/workspace/world_courts"
GM = "/workspace/global_municipalities/global_municipalities_candidate.csv"
UA = "world_courts/0.1 (open court-data research; github.com/endomorphosis)"
NOW = lambda: datetime.datetime.utcnow().isoformat() + "Z"

def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(saint|st)\b\.?", "st", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()

AU_PREFIX = re.compile(r"^(aboriginal shire of|rural city of|regional council of|city of|shire of|town of|municipality of|district council of|council of the city of|borough of|city of)\s+")
AU_SUFFIX = re.compile(r"\s+(city council|shire council|regional council|council|city|shire|municipality|regional|town)$")

def core(name, cc):
    n = norm(name)
    if cc == "AU":
        n = AU_PREFIX.sub("", n); n = AU_SUFFIX.sub("", n); n = AU_SUFFIX.sub("", n)
    elif cc == "GB":
        n = re.sub(r"^(city of|royal borough of|london borough of|borough of|county of)\s+", "", n)
        n = re.sub(r"\s+(city|county|council|borough|district|unitary authority)$", "", n)
    else:
        n = re.sub(r"^(city of|town of|municipality of|village of|ville de|municipalite de)\s+", "", n)
        n = re.sub(r"\s+(city|town|village|county|municipality)$", "", n)
    return n

_RANK = {"municipality": 0, "unitary_authority": 1, "council_area": 1, "principal_area": 1, "district": 2, "county": 3,
         "parish": 4, "community": 4, "territory": 5, "province": 6, "state": 6, "adm1": 6}

@functools.lru_cache(None)
def place_index(cc):
    idx = {}
    with open(GM, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["country_code"] != cc or not r.get("place_id"):
                continue
            idx.setdefault(core(r["place_name"], cc), []).append((_RANK.get(r["admin_level"], 7), r["place_id"], r["place_name"], r["admin_level"], r.get("population") or ""))
    return idx

def pop(x):
    try: return -float(x[4])
    except Exception: return 0

def match_place(city, cc, extra=()):
    """Return (place_ids, method). Name match of city (and optional extra names) to global_municipalities wd: ids."""
    idx = place_index(cc); out = []; method = None
    for nm in [city, *extra]:
        if not nm: continue
        c = core(nm, cc)
        cands = idx.get(c)
        if not cands and cc == "GB":
            cands = idx.get(c + " city") or idx.get(c + " county")
        if cands:
            cands = sorted(cands, key=lambda x: (x[0], pop(x)))
            if cands[0][1] not in out: out.append(cands[0][1])
            method = method or "name"
    return out, method

@functools.lru_cache(None)
def subdivision_place(cc, name):
    """place id for a state/province/territory/nation by name"""
    idx = place_index(cc)
    for k in (core(name, cc), norm(name)):
        for c in sorted(idx.get(k, []), key=lambda x: x[0]):
            if c[3] in ("state", "province", "territory", "adm1", "county", "council_area", "principal_area"):
                return c[1]
    return None

def get(url, delay=1.0, data=None, headers=None, timeout=60, binary=False):
    h = {"User-Agent": UA}; h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    time.sleep(delay)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        b = r.read()
    return b if binary else b.decode("utf-8", "replace")

def postcodes_io(pcs):
    """bulk geocode UK postcodes via postcodes.io (open, OGL/ONS). returns {pc:(lat,lon,admin_district)}"""
    out = {}; pcs = sorted({p for p in pcs if p})
    for i in range(0, len(pcs), 100):
        body = json.dumps({"postcodes": pcs[i:i+100]}).encode()
        try:
            r = json.loads(get("https://api.postcodes.io/postcodes", data=body, headers={"Content-Type": "application/json"}, delay=1.0))
        except Exception as e:
            print("postcodes.io err", e); continue
        for it in r.get("result", []):
            res = it.get("result")
            if res and res.get("latitude") is not None:
                out[it["query"]] = (res["latitude"], res["longitude"], res.get("admin_district"), res.get("country"), res.get("region"), res.get("parish"))
    return out

_NOM = f"{ROOT}/data/ref/nominatim_cache.json"
_NC = None
def nominatim(q, cc=None):
    """Nominatim search, <=1 req/s, cached (atomic saves). Returns (lat,lon) or None."""
    global _NC
    if _NC is None:
        try: _NC = json.load(open(_NOM))
        except Exception: _NC = {}
    k = f"{cc}|{q}"
    if k in _NC: return tuple(_NC[k]) if _NC[k] else None
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({"q": q, "format": "jsonv2", "limit": 1, **({"countrycodes": cc.lower()} if cc else {})})
    try:
        r = json.loads(get(url, delay=1.2))
        v = (float(r[0]["lat"]), float(r[0]["lon"])) if r else None
    except Exception as e:
        print("nominatim err", e); return None
    _NC[k] = v
    if len(_NC) % 10 == 0:
        json.dump(_NC, open(_NOM + ".tmp", "w")); os.replace(_NOM + ".tmp", _NOM)
    return v

def nominatim_flush():
    if _NC is not None:
        json.dump(_NC, open(_NOM + ".tmp", "w")); os.replace(_NOM + ".tmp", _NOM)

def haversine(a, b):
    from math import radians, sin, cos, asin, sqrt
    la1, lo1, la2, lo2 = map(radians, (a[0], a[1], b[0], b[1]))
    h = sin((la2-la1)/2)**2 + cos(la1)*cos(la2)*sin((lo2-lo1)/2)**2
    return 12742000 * asin(sqrt(h))

def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", norm(s)).strip("-")

def rec(**kw):
    base = dict(court_id=None, record_type="courthouse", name=None, name_local=None, level="other", court_system="national", country_code=None,
                subdivision=None, jurisdiction=None, parent_court_id=None, address={"street": None, "city": None, "postcode": None, "region": None, "country": None},
                geo={"lat": None, "lon": None}, phone=None, website=None, wikidata=None, place_ids=[], source_url=None, source_kind="official",
                site_policy="robots_allowed", retrieved_at=NOW(), license=None, sources=[])
    base.update(kw)
    if not base["sources"]:
        base["sources"] = [{"source_url": base["source_url"], "site_policy": base["site_policy"], "source_kind": base["source_kind"]}]
    return base

def wjl(path, rows):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        for r in rows: f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    os.replace(tmp, path)

def rjl(path):
    return [json.loads(l) for l in open(path)] if os.path.exists(path) else []

def merge_dedupe(primary, secondary, dist_m=150, name_sim=0.4):
    """Add secondary rows (e.g. OSM) that do not duplicate a primary row (same place within dist_m and shared name tokens)."""
    def toks(n): return {t for t in norm(n).split() if t not in {"court", "courts", "house", "the", "of", "and", "county", "crown", "magistrates", "sheriff", "tribunal", "family", "justice", "peace", "centre", "courthouse", "district", "supreme", "high", "local", "law", "building", "provincial", "magistrate"}}
    added = []; dup = 0
    pts = [(r["geo"]["lat"], r["geo"]["lon"], r) for r in primary if r["geo"]["lat"] is not None]
    for s in secondary:
        g = s["geo"]; dupe = None
        if g["lat"] is not None:
            for la, lo, p in pts:
                if abs(la - g["lat"]) < 0.004 and abs(lo - g["lon"]) < 0.006 and haversine((la, lo), (g["lat"], g["lon"])) <= dist_m:
                    dupe = p; break
        if dupe is None:
            # name+city match without geo proximity
            for p in primary:
                if p["address"].get("city") and s["address"].get("city") and norm(p["address"]["city"]) == norm(s["address"]["city"]) and norm(p["name"]) == norm(s["name"]):
                    dupe = p; break
        if dupe is not None:
            dup += 1
            dupe.setdefault("sources", []).extend(s["sources"])
            if dupe.get("wikidata") is None and s.get("wikidata"): dupe["wikidata"] = s["wikidata"]
        else:
            added.append(s)
    return primary + added, dup, len(added)
