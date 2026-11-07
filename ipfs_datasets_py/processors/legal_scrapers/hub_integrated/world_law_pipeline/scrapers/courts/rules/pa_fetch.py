import json
from rules_common import *
C=json.load(open("pa_chapters.json"))
ok={}
for t,chs in C.items():
    t=int(t);ok[t]=[]
    for n in sorted(set(chs)):
        try: b,u,pol=cached(f"https://www.pacodeandbulletin.gov/secure/pacode/data/{t:03d}/chapter{n}/{t:03d}_{n:04d}.pdf",f"pa_{t}_{n}.pdf")
        except Exception as e: print(t,n,"err",e,flush=True);continue
        if b and b[:4]==b"%PDF": ok[t].append(n);print(t,n,len(b),flush=True)
        else: print(t,n,"none",flush=True)
    json.dump(ok,open("pa_ok.json","w"))
print("DONE",flush=True)
