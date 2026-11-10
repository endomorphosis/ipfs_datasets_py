import re,sys,json
from rules_common import *
B="https://www.leg.state.nv.us/Division/Legal/LawLibrary/CourtRules/"
idx,u,pol=cached(B,"nv_index.html")
links=re.findall(r'href="([A-Za-z_]+\.html)">([^<]+)<',idx.decode("utf-8","replace"))
skip={"RPC.html","Conduct_CWC.html","SCR_RJE.html"}
out=[]
for f,t in links:
    if f in skip: continue
    b,u,pol=cached(B+f,"nv_"+f)
    out.append({"file":f,"title":t.strip(),"url":u,"policy":pol,"bytes":len(b) if b else 0})
    print(f,len(b) if b else None,pol,flush=True)
json.dump(out,open(ROOT+"/rules/raw/nv_manifest.json","w"),indent=1)
