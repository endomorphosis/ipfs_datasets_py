"""Fill place_ids on US courthouse rows: Census reverse geocoder (place/cousub/county GEOID) -> global_municipalities census_geoid -> gnis:/wd: place_id; fallback city+state name match."""
import csv,json,sys,re,time,urllib.request,os,concurrent.futures as cf
GM="/workspace/global_municipalities/global_municipalities_candidate.csv"
CACHE="/workspace/world_courts/data/us/cache/census_rev.jsonl"
U="https://geocoding.geo.census.gov/geocoder/geographies/coordinates?x={lon}&y={lat}&benchmark=Public_AR_Current&vintage=Current_Current&layers=Counties,Incorporated%20Places,County%20Subdivisions&format=json"
def norm(s): return re.sub(r'^(city|town|village|borough|township|county) of ','',(s or '').lower()).replace(' city','').strip()
def load_gm():
    geo={};nm={}
    for x in csv.DictReader(open(GM)):
        if x['country_code']!='US':continue
        if x['census_geoid']: geo[x['census_geoid']]=x['place_id']
        if x['admin_level']!='county': nm.setdefault((norm(x['place_name']),x['state_code']),x['place_id'])
    return geo,nm
def rev(key):
    lat,lon=key
    for a in range(3):
        try:
            g=json.load(urllib.request.urlopen(U.format(lat=lat,lon=lon),timeout=30))["result"]["geographies"]
            return {k:[v.get("GEOID") for v in g.get(k,[])] for k in ("Counties","Incorporated Places","County Subdivisions")}
        except Exception: time.sleep(3)
def main(inp,out):
    rows=[json.loads(l) for l in open(inp)];geo,nm=load_gm()
    cache={}
    if os.path.exists(CACHE):
        for l in open(CACHE): d=json.loads(l);cache[tuple(d["k"])]=d["v"]
    todo=list({(round(r['geo']['lat'],5),round(r['geo']['lon'],5)) for r in rows}-set(cache))
    cw=open(CACHE,"a")
    with cf.ThreadPoolExecutor(4) as ex:
        for k,v in zip(todo,ex.map(rev,todo)):
            if v is not None: cache[k]=v;cw.write(json.dumps({"k":k,"v":v})+"\n")
    stats={"place":0,"county":0,"any":0,"name":0}
    with open(out,"w") as f:
        for r in rows:
            v=cache.get((round(r['geo']['lat'],5),round(r['geo']['lon'],5))) or {};ids=[];m=None
            for gid in v.get("Incorporated Places",[])+v.get("County Subdivisions",[]):
                if gid in geo: ids.append(geo[gid]);m="census_geo"
            if not ids and r['address'].get('city'):
                p=nm.get((norm(r['address']['city']),r['subdivision'][3:]))
                if p: ids.append(p);m="name";stats["name"]+=1
            if ids: stats["place"]+=1
            cids=[geo[g] for g in v.get("Counties",[]) if g in geo]
            if cids: stats["county"]+=1
            r["place_ids"]=list(dict.fromkeys(ids+cids));r["county_fips"]=(v.get("Counties") or [None])[0];r["place_match_method"]=m
            if r["place_ids"]: stats["any"]+=1
            f.write(json.dumps(r)+"\n")
    stats["total"]=len(rows);print(json.dumps(stats))
if __name__=="__main__": main(sys.argv[1],sys.argv[2])
