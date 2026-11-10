import sys,re,json
sys.path.insert(0,"/workspace/world_courts/scrapers/courts/rules")
from rules_common import *
b=open(RAW+"/intl_qc_find.html","rb").read().decode("utf-8","replace")
L=sorted(set(re.findall(r'href="(/nous-joindre/trouver-un-palais-de-justice/(?:palais|point)[^"/]+)"',b)))
print(len(L),flush=True)
for p in L:
    u="https://justice.gouv.qc.ca"+p
    try:
        _,_,pol=cached(u,"intl_qc_"+p.split("/")[-1]+".html");print(p,pol,flush=True)
    except Exception as e: print(p,"ERR",e,flush=True)
