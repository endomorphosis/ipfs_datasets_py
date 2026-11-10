import sys,re
sys.path.insert(0,"/workspace/world_courts/scrapers/courts/rules")
from rules_common import *
h=open(RAW+"/intl_ca_mb_pc.html","rb").read().decode()
L=[("mb","https://www.manitobacourts.mb.ca"+p) for p in sorted(set(re.findall(r'href="(/provincial-court/locations-and-contact-info/location/[^"]+)"',h)))]
h=open(RAW+"/intl_ca_ns.html","rb").read().decode()
L+=[("ns","https://www.courts.ns.ca"+p) for p in sorted(set(re.findall(r'href="(/locations/[^"]+)"',h)))]
for k,u in L:
    try: cached(u,"intl_ca_%s_%s.html"%(k,u.rstrip("/").split("/")[-1]));print(u,flush=True)
    except Exception as e: print("ERR",u,e,flush=True)
