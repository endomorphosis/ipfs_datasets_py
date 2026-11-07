"""wave 12 host discovery (DNS only, no HTTP): candidate official hosts per place from naming patterns + candidate-CSV official_site rows.
Writes afme/w12/<cc>_hosts.csv (place_id,place_name,admin_level,population,host,source). Robots probing happens later in afme_w12_cfg.py (1 GET/host)."""
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import csv,socket,re,sys,unicodedata,os
from concurrent.futures import ThreadPoolExecutor
socket.setdefaulttimeout(5)
PAT={"RW":["{n}.gov.rw"],
 "SN":["commune-{n}.sn","communede{n}.sn","ville{n}.sn","villede{n}.sn","mairie{n}.sn","mairiede{n}.sn","commune{n}.sn","{n}.gouv.sn"],
 "MG":["commune-{n}.mg","commune{n}.mg","cu-{n}.mg","cu{n}.mg","mairie-{n}.mg","{n}.gov.mg","commune-urbaine-{n}.mg"],
 "ML":["mairie{n}.ml","mairiede{n}.ml","commune{n}.ml","communede{n}.ml","{n}.gouv.ml","mairie-{n}.ml"],
 "GN":["{n}.gov.gn","mairie{n}.gov.gn","mairiede{n}.gov.gn","mairiede{n}.org","mairie{n}.org","commune{n}.gov.gn"],
 "ET":["{n}.gov.et","{n}city.gov.et","{n}cityadmin.gov.et","{n}municipality.gov.et","{n}city.gov.et"]}
GOV=re.compile(r"(?i)(\.gov\.|\.gouv\.|\.gov$|mairie|commune|ville|municipal|city|district|cityadmin)")
def slug(s,sep=""):
    s=unicodedata.normalize("NFKD",s).encode("ascii","ignore").decode().lower()
    s=re.sub(r"\b(commune|district|urbaine|rurale|de|city|town|woreda|municipality|sector)\b"," ",s)
    return re.sub(r"[^a-z0-9]+",sep,s).strip(sep)
import requests,time
def res(h): return h if (_res(h) or _res("www."+h)) else None
def _res(h):   # local resolver is a fake-IP proxy (everything -> 198.18.0.1), so use public DoH; NXDOMAIN (Status 3) = absent
    for i in range(3):
        try:
            j=requests.get("https://cloudflare-dns.com/dns-query",params={"name":h,"type":"A"},headers={"accept":"application/dns-json"},timeout=10).json()
            return h if j.get("Status")==0 and any(a.get("type") in (1,5) for a in j.get("Answer",[])) else None
        except Exception: time.sleep(2)
    return None
os.makedirs("afme/w12",exist_ok=True)
for cc in sys.argv[1:]:
    R=[r for r in csv.DictReader(open((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + '/global_municipalities_candidate.csv'))) if r['country_code']==cc]
    R.sort(key=lambda r:-float(r['population'] or 0)); R=R[:300] if cc!='RW' else R
    cand=[]
    for r in R:
        if r['url_class']=='official_site' and r['source_url'].startswith('http'):
            h=re.sub(r"^www\.","",re.sub(r"^https?://([^/]+).*",r"\1",r['source_url']).lower())
            cand.append((r,h,"candidate_csv"))
        if cc=="RW" and r['admin_level']!='district': continue
        if cc=="ET" and len(cand)>2000: continue
        for sep in ("","-"):
            n=slug(r['place_name'],sep)
            if len(n)<3: continue
            for p in PAT[cc]: cand.append((r,p.format(n=n),"pattern"))
    hs=sorted({h for _,h,_ in cand})
    with ThreadPoolExecutor(8) as ex: ok=set(filter(None,ex.map(res,hs)))
    seen=set(); out=[]
    for r,h,src in cand:
        if h in ok and h not in seen and (src=="pattern" or GOV.search(h)):
            seen.add(h); out.append([r['place_id'],r['place_name'],r['admin_level'],r['population'],h,src])
    w=csv.writer(open(f"afme/w12/{cc.lower()}_hosts.csv","w")); w.writerow(["place_id","place_name","admin_level","population","host","source"]); w.writerows(out)
    print(cc,"places",len(R),"candidates",len(hs),"resolved",len(ok),"kept",len(out),flush=True)
