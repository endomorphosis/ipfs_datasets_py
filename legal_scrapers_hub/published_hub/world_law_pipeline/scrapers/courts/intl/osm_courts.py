"""OSM amenity=courthouse for GB, CA, AU by ISO3166-2 admin-4 region. (c) OpenStreetMap contributors, ODbL.
Usage: osm_courts.py CC  -> data/<cc>/<cc>_courthouses_osm.jsonl"""
import json,sys,time,datetime,urllib.request,urllib.parse,os
OVP="https://overpass-api.de/api/interpreter"
REG={"GB":["GB-ENG","GB-SCT","GB-WLS","GB-NIR"],
"CA":["CA-AB","CA-BC","CA-MB","CA-NB","CA-NL","CA-NS","CA-NT","CA-NU","CA-ON","CA-PE","CA-QC","CA-SK","CA-YT"],
"AU":["AU-ACT","AU-NSW","AU-NT","AU-QLD","AU-SA","AU-TAS","AU-VIC","AU-WA"]}
def q(rid): return f'[out:json][timeout:240];area["ISO3166-2"="{rid}"]->.a;nwr["amenity"="courthouse"](area.a);out center tags;'
def main(cc):
    out=f"/workspace/world_courts/data/{cc.lower()}/{cc.lower()}_courthouses_osm.jsonl";os.makedirs(os.path.dirname(out),exist_ok=True)
    f=open(out,"w");tot=0
    for rid in REG[cc]:
        for a in range(4):
            try: d=json.load(urllib.request.urlopen(urllib.request.Request(OVP,data=urllib.parse.urlencode({"data":q(rid)}).encode(),headers={"User-Agent":"world_courts/0.1 (research)"}),timeout=300));break
            except Exception as e: print(rid,"retry",e,file=sys.stderr);time.sleep(40)
        else: continue
        now=datetime.datetime.utcnow().isoformat()+"Z";n=0
        for e in d["elements"]:
            t=e.get("tags",{});lat=e.get("lat") or e.get("center",{}).get("lat");lon=e.get("lon") or e.get("center",{}).get("lon")
            if lat is None: continue
            rec={"osm_id":f"{e['type']}/{e['id']}","name":t.get("name") or t.get("official_name"),"name_local":t.get("name:fr") or t.get("name:cy") or t.get("name:gd"),"subdivision":rid,"country_code":cc,
              "street":" ".join(x for x in [t.get("addr:housenumber"),t.get("addr:street")] if x) or None,"city":t.get("addr:city") or t.get("addr:town") or t.get("addr:suburb"),"postcode":t.get("addr:postcode"),
              "lat":lat,"lon":lon,"phone":t.get("phone") or t.get("contact:phone"),"website":t.get("website") or t.get("contact:website"),"wikidata":t.get("wikidata"),"operator":t.get("operator"),"court_type":t.get("court:type") or t.get("courthouse"),"retrieved_at":now}
            f.write(json.dumps(rec)+"\n");n+=1
        tot+=n;print(rid,n,tot,file=sys.stderr,flush=True);f.flush();time.sleep(8)
if __name__=="__main__": main(sys.argv[1])
