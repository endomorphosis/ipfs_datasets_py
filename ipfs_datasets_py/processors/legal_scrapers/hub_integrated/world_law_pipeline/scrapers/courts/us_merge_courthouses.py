"""Merge official-directory courthouse rows with OSM rows.
1) geocode directory addresses with Census batch geocoder (returns place/county via 'geographies')
2) dedupe: same (street-number+zip) or within 150 m and name token overlap/same zip -> merge (official fields win for name/address; keep both sources)
3) unmatched directory rows become new courthouses; then place_ids via us_place_match logic."""
import json,sys,glob,math,re,io,csv,urllib.request,uuid,hashlib
sys.path.insert(0,"/workspace/world_courts/scrapers/courts")
import us_place_match as pm
D="/workspace/world_courts/data/us/"
def batch_geocode(rows):
    res={}
    for i in range(0,len(rows),2000):
        buf=io.StringIO();w=csv.writer(buf)
        for j,r in enumerate(rows[i:i+2000]): a=r["address"];w.writerow([i+j,a["street"],a["city"],a["region"],a["postcode"]])
        b="----"+uuid.uuid4().hex
        body=(f"--{b}\r\nContent-Disposition: form-data; name=\"benchmark\"\r\n\r\nPublic_AR_Current\r\n--{b}\r\nContent-Disposition: form-data; name=\"vintage\"\r\n\r\nCurrent_Current\r\n--{b}\r\nContent-Disposition: form-data; name=\"addressFile\"; filename=\"a.csv\"\r\nContent-Type: text/csv\r\n\r\n"+buf.getvalue()+f"\r\n--{b}--\r\n").encode()
        t=urllib.request.urlopen(urllib.request.Request("https://geocoding.geo.census.gov/geocoder/geographies/addressbatch",data=body,headers={"Content-Type":"multipart/form-data; boundary="+b}),timeout=600).read().decode()
        for rec in csv.reader(io.StringIO(t)):
            if len(rec)>5 and rec[2]=="Match":
                lon,lat=map(float,rec[5].split(","));res[int(rec[0])]={"lat":lat,"lon":lon,"county_fips":(rec[8]+rec[9]) if len(rec)>9 else None}
    return res
def hav(a,b): 
    R=6371000;p1,p2=math.radians(a["lat"]),math.radians(b["lat"]);dl=math.radians(b["lon"]-a["lon"]);dp=p2-p1
    return 2*R*math.asin(math.sqrt(math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2))
def toks(s): return set(re.findall(r"[a-z]{4,}",(s or "").lower()))-{"court","county","courthouse","district","circuit","state","office","clerk","building","justice","center"}
def main():
    osm=[json.loads(l) for l in open(D+"us_courthouses_osm_placed.jsonl")]
    dr=[json.loads(l) for f in sorted(glob.glob(D+"dir_part*.jsonl")) for l in open(f)]
    # drop obviously non-court addresses (no court-ish name)
    dr=[r for r in dr if r["name"]]
    for r in dr:
        st=r["address"]["street"].split("\n")[-1].strip(" ,");r["address"]["street"]=st
        r["name"]=r["name"].strip(" *|,") ;r["needs_review"]=True
        r["is_mailing_address"]=bool(re.match(r"(?i)p\.?\s*o\.?\s*box",st))
    dr=[r for r in dr if not r["is_mailing_address"] and re.match(r"\d+\s+\S",r["address"]["street"])]
    g=batch_geocode(dr);print("dir rows",len(dr),"geocoded",len(g),file=sys.stderr)
    for i,r in enumerate(dr):
        if i in g: r["geo"]={"lat":g[i]["lat"],"lon":g[i]["lon"]};r["county_fips"]=g[i]["county_fips"]
    for r in osm: r["sources"]=[{"source_url":r["source_url"],"site_policy":r["site_policy"],"source_kind":"osm"}]
    merged=0;new=[]
    grid={}
    for k,r in enumerate(osm): grid.setdefault((r["subdivision"],round(r["geo"]["lat"],2),round(r["geo"]["lon"],2)),[]).append(k)
    for r in dr:
        best=None
        if r["geo"]:
            la,lo=round(r["geo"]["lat"],2),round(r["geo"]["lon"],2)
            for dla in (-0.01,0,0.01):
                for dlo in (-0.01,0,0.01):
                    for k in grid.get((r["subdivision"],round(la+dla,2),round(lo+dlo,2)),[]):
                        d=hav(r["geo"],osm[k]["geo"])
                        if d<150 or (d<600 and toks(r["name"])&toks(osm[k]["name"])):
                            if best is None or d<best[0]: best=(d,k)
        src={"source_url":r["source_url"],"site_policy":r["site_policy"],"source_kind":r["source_kind"],"name":r["name"],"address":r["address"]}
        if best:
            o=osm[best[1]];o["sources"].append(src);merged+=1
            if not o["address"].get("street"): o["address"]=r["address"]
            o["official_name"]=o.get("official_name") or r["name"]
        else:
            r["court_id"]="usdir:"+hashlib.sha1((r["subdivision"]+r["address"]["street"]+r["address"]["postcode"]).lower().encode()).hexdigest()[:12]
            r["sources"]=[src];new.append(r)
    geo,nm=pm.load_gm()
    for r in new:
        ids=[];p=nm.get((pm.norm(r["address"]["city"]),r["subdivision"][3:]))
        if p: ids.append(p)
        if r.get("county_fips") and r["county_fips"] in geo: ids.append(geo[r["county_fips"]])
        r["place_ids"]=ids;r["place_match_method"]="name+county_fips" if ids else None
    allr=osm+new
    with open(D+"us_courthouses.jsonl","w") as f:
        for r in allr: f.write(json.dumps(r)+"\n")
    print(json.dumps({"osm":len(osm),"directory_rows":len(dr),"dir_geocoded":len(g),"merged_into_osm":merged,"new_from_directory":len(new),"total":len(allr),
        "with_place_ids":sum(1 for r in allr if r["place_ids"]),"multi_source":sum(1 for r in allr if len(r["sources"])>1)}))
if __name__=="__main__": main()
