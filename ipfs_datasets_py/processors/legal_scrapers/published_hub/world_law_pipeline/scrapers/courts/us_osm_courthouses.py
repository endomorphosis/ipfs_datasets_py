"""Collect US courthouse locations from OpenStreetMap (amenity=courthouse) via Overpass, per state.
Output follows schema/world_courts_schema.json 'courthouses'. Data (c) OSM contributors, ODbL."""
import json,sys,time,datetime,re,urllib.request,urllib.parse
from us_state_judiciaries import STATES
OVP="https://overpass-api.de/api/interpreter"
def classify(n):
    n=(n or "").lower()
    for k,v in [("supreme","supreme"),("appeal","appellate"),("united states","federal_district"),("federal","federal_district"),("municipal","municipal"),("city court","municipal"),("probate","probate"),("family","family"),("juvenile","juvenile"),("justice court","trial_limited"),("magistrate","trial_limited"),("district court","trial_general"),("circuit","trial_general"),("superior","trial_general"),("county court","trial_limited"),("tribal","other")]:
        if k in n: return v
    return None
def run(out):
    f=open(out,"w");tot=0
    for st in STATES:
        q=f'[out:json][timeout:180];area["ISO3166-2"="US-{st}"][admin_level=4]->.a;nwr["amenity"="courthouse"](area.a);out center tags;'
        for attempt in range(4):
            try:
                d=json.load(urllib.request.urlopen(urllib.request.Request(OVP,data=urllib.parse.urlencode({"data":q}).encode(),headers={"User-Agent":"world_courts/0.1"}),timeout=240));break
            except Exception as e: print(st,"retry",e,file=sys.stderr);time.sleep(30)
        else: continue
        now=datetime.datetime.utcnow().isoformat()+"Z";n=0
        for e in d["elements"]:
            t=e.get("tags",{});lat=e.get("lat") or e.get("center",{}).get("lat");lon=e.get("lon") or e.get("center",{}).get("lon")
            name=t.get("name")
            rec={"court_id":f"osm:{e['type']}/{e['id']}","name":name,"level":classify(name),"court_system":"federal" if classify(name)=="federal_district" else ("municipal" if classify(name)=="municipal" else "state"),
                 "country_code":"US","subdivision":f"US-{st}","jurisdiction":t.get("addr:county"),"parent_court_id":None,
                 "address":{"street":" ".join(x for x in [t.get("addr:housenumber"),t.get("addr:street")] if x) or None,"city":t.get("addr:city"),"postcode":t.get("addr:postcode"),"region":st,"country":"US"},
                 "geo":{"lat":lat,"lon":lon},"phone":t.get("phone"),"website":t.get("website"),"wikidata":t.get("wikidata"),"place_ids":[],
                 "source_url":f"https://www.openstreetmap.org/{e['type']}/{e['id']}","source_kind":"osm","site_policy":"open_license:ODbL","retrieved_at":now}
            f.write(json.dumps(rec)+"\n");n+=1
        tot+=n;print(st,n,tot,file=sys.stderr);f.flush();time.sleep(5)
if __name__=="__main__": run(sys.argv[1])
